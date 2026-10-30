"""POST /api/jpg-to-pdf: upload images, get one PDF with a page per image."""

import gc
import shutil
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, File, Form, UploadFile
from starlette.concurrency import run_in_threadpool

from app.core.config import get_settings
from app.core.errors import (
    INVALID_REQUEST,
    NOT_IMAGE,
    NOT_PDF,
    TOO_LARGE,
    TOO_MANY_FILES,
    AppError,
)
from app.schemas.jobs import JpgToPdfResponse
from app.services.jpg_to_pdf import (
    convert_images_to_pdf,
    not_image_message,
    parse_page_size,
)
from app.utils.storage import (
    delete_job,
    get_output_dir,
    get_upload_dir,
    new_job_id,
    write_meta,
)
from app.utils.uploads import (
    looks_like_jpeg,
    looks_like_png,
    safe_display_name,
    save_upload,
)

router = APIRouter()

# The type is unknown until the bytes are sniffed, so uploads get a neutral
# generated name; a client file name is never used on disk.
UPLOAD_SUFFIX = ".img"
_MEGABYTE = 1024 * 1024


def _remove_folder(path: Path) -> None:
    """Remove a folder, retrying once after a garbage collection.

    On Windows a file that is still open cannot be deleted. A PyMuPDF or
    Pillow object that is no longer referenced but not yet freed can be the
    holder, so collecting garbage and trying again usually clears it. Whatever
    still survives is left for the sweeper. (Same helper as routes/compress.py
    and routes/pdf_to_jpg.py, copied because those files are not to be touched.)
    """
    shutil.rmtree(path, ignore_errors=True)
    if path.exists():
        gc.collect()
        shutil.rmtree(path, ignore_errors=True)


def _translate(error: AppError, position: int, max_total_bytes: int) -> AppError:
    """Re-word what save_upload says (it is written for PDFs) for an image batch.

    The size cap here is the total of all files, and an empty file is reported
    by save_upload as not_pdf. Anything else is returned unchanged.
    """
    if error.code == TOO_LARGE:
        limit_mb = max_total_bytes // _MEGABYTE
        message = (
            f"These images are larger than {limit_mb} MB in total. "
            "Please choose fewer or smaller images."
            if limit_mb >= 1
            else None
        )
        return AppError(TOO_LARGE, message)
    if error.code == NOT_PDF:
        return AppError(
            NOT_IMAGE,
            f"Image {position} is empty. Please choose JPG or PNG images "
            "that are not empty.",
        )
    return error


async def _save_images(
    files: list[UploadFile], upload_dir: Path, max_total_bytes: int
) -> list[Path]:
    """Stream every file to the upload folder, in order, and sniff each one.

    max_total_bytes caps the sum of all files, so each file gets whatever the
    earlier files left over. A file that is not a JPEG or PNG by its first
    bytes is rejected at once, naming its position.
    """
    saved: list[Path] = []
    total = 0
    for position, upload in enumerate(files, start=1):
        destination = upload_dir / f"{position:03d}{UPLOAD_SUFFIX}"
        try:
            total += await save_upload(upload, destination, max_total_bytes - total)
        except AppError as error:
            translated = _translate(error, position, max_total_bytes)
            if translated is error:
                raise
            raise translated from error
        if not (looks_like_jpeg(destination) or looks_like_png(destination)):
            raise AppError(NOT_IMAGE, not_image_message(position))
        saved.append(destination)
    return saved


@router.post("/jpg-to-pdf", response_model=JpgToPdfResponse)
async def convert(
    files: Annotated[list[UploadFile], File()],
    page_size: Annotated[str | None, Form()] = None,
) -> JpgToPdfResponse:
    """Combine JPG and PNG images into one PDF, in the order they were sent.

    The upload folder is removed on every path; the output folder is removed on
    every failure, so a failed job leaves nothing behind.
    """
    chosen_page_size = parse_page_size(page_size)
    settings = get_settings()
    if not files:
        raise AppError(INVALID_REQUEST)
    if len(files) > settings.max_images:
        raise AppError(
            TOO_MANY_FILES,
            f"You chose {len(files)} images, and the limit is "
            f"{settings.max_images}. Please choose fewer images and try again.",
        )

    job_id = new_job_id()
    upload_dir = get_upload_dir(job_id, create=True)
    output_dir = get_output_dir(job_id, create=True)
    succeeded = False
    try:
        image_paths = await _save_images(
            files, upload_dir, settings.max_upload_mb * _MEGABYTE
        )

        result = await run_in_threadpool(
            convert_images_to_pdf, image_paths, output_dir, chosen_page_size
        )

        first_name = safe_display_name(files[0].filename)
        download_name = f"{first_name}.pdf" if len(files) == 1 else "images.pdf"
        write_meta(
            job_id,
            {
                "original_name": first_name,
                "result_name": result.result_name,
                "download_name": download_name,
                "page_size": chosen_page_size,
                "page_count": result.page_count,
                "total_input_size": result.total_input_size,
                "result_size": result.result_size,
            },
        )
        response = JpgToPdfResponse(
            job_id=job_id,
            page_count=result.page_count,
            total_input_size=result.total_input_size,
            result_size=result.result_size,
            page_size=chosen_page_size,
            download_url=f"/api/jobs/{job_id}/download",
        )
        succeeded = True
        return response
    finally:
        for upload in files:
            await upload.close()
        _remove_folder(upload_dir)
        if not succeeded:
            delete_job(job_id)