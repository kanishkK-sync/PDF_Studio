"""POST /api/jpg-to-pdf: upload pictures, get one PDF back as a job."""

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, File, Form, UploadFile
from starlette.concurrency import run_in_threadpool

from app.core.config import get_settings
from app.core.errors import NOT_IMAGE, NOT_PDF, TOO_LARGE, TOO_MANY_FILES, AppError
from app.schemas.jobs import JpgToPdfResponse
from app.services.jpg_to_pdf import (
    RESULT_PDF,
    convert_images_to_pdf,
    parse_page_size,
)
from app.utils.cleanup import remove_folder
from app.utils.storage import (
    delete_job,
    get_output_dir,
    get_upload_dir,
    new_job_id,
    write_meta,
)
from app.utils.uploads import safe_display_name, save_upload

router = APIRouter()

_MEGABYTE = 1024 * 1024


async def _save_image(
    upload: UploadFile, destination: Path, number: int, max_bytes: int
) -> int:
    """Stream one picture to disk under a generated name.

    save_upload reports an empty file as not_pdf, which would be a confusing
    message here, so that one case is turned into a picture-specific error.
    """
    try:
        return await save_upload(upload, destination, max_bytes)
    except AppError as exc:
        if exc.code == NOT_PDF:
            raise AppError(
                NOT_IMAGE,
                f"Image {number} is empty. Please choose pictures that are not empty.",
            ) from exc
        raise


@router.post("/jpg-to-pdf", response_model=JpgToPdfResponse)
async def convert(
    files: Annotated[list[UploadFile], File()],
    page_size: Annotated[str | None, Form()] = None,
) -> JpgToPdfResponse:
    """Convert uploaded JPG or PNG pictures into one PDF, in the order sent.

    The upload folder is removed on every path; the output folder is removed on
    every failure, so a failed job leaves nothing behind.
    """
    chosen_size = parse_page_size(page_size)
    settings = get_settings()
    if len(files) > settings.max_images:
        raise AppError(
            TOO_MANY_FILES,
            f"You chose {len(files)} images, and the limit is "
            f"{settings.max_images}. Please choose fewer images and try again.",
        )

    max_bytes = settings.max_upload_mb * _MEGABYTE
    job_id = new_job_id()
    upload_dir = get_upload_dir(job_id, create=True)
    output_dir = get_output_dir(job_id, create=True)
    succeeded = False
    try:
        saved: list[Path] = []
        total_size = 0
        for number, upload in enumerate(files, start=1):
            destination = upload_dir / f"{number:03d}.bin"
            total_size += await _save_image(upload, destination, number, max_bytes)
            if total_size > max_bytes:
                raise AppError(
                    TOO_LARGE,
                    f"These images add up to more than {settings.max_upload_mb} MB. "
                    "Please choose fewer or smaller images and try again.",
                )
            saved.append(destination)

        result = await run_in_threadpool(
            convert_images_to_pdf, saved, output_dir, chosen_size
        )

        first_name = safe_display_name(files[0].filename)
        download_name = f"{first_name}.pdf" if len(files) == 1 else "images.pdf"
        write_meta(
            job_id,
            {
                "original_name": first_name,
                "result_name": RESULT_PDF,
                "download_name": download_name,
                "page_size": chosen_size,
                "page_count": result.page_count,
                "file_count": len(files),
                "total_input_size": total_size,
                "result_size": result.result_size,
            },
        )
        response = JpgToPdfResponse(
            job_id=job_id,
            page_count=result.page_count,
            total_input_size=total_size,
            result_size=result.result_size,
            page_size=chosen_size,
            download_name=download_name,
            download_url=f"/api/jobs/{job_id}/download",
        )
        succeeded = True
        return response
    finally:
        for upload in files:
            await upload.close()
        remove_folder(upload_dir)
        if not succeeded:
            delete_job(job_id)