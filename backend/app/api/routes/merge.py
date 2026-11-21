"""POST /api/merge: combine multiple PDFs into one."""

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, File, UploadFile
from starlette.concurrency import run_in_threadpool

from app.core.config import get_settings
from app.core.errors import (
    INVALID_REQUEST,
    NOT_PDF,
    TOO_LARGE,
    TOO_MANY_FILES,
    AppError,
)
from app.schemas.jobs import MergeResponse
from app.services.pdf_merge import merge_pdfs
from app.utils.cleanup import remove_folder
from app.utils.storage import (
    delete_job,
    get_output_dir,
    get_upload_dir,
    new_job_id,
    write_meta,
)
from app.utils.uploads import looks_like_pdf, save_upload

router = APIRouter()

UPLOAD_SUFFIX = ".pdf"
DOWNLOAD_NAME = "merged.pdf"
_MEGABYTE = 1024 * 1024


def _translate(error: AppError, position: int, max_total_bytes: int) -> AppError:
    """Re-word what save_upload says for a multi-file batch.

    The size cap is the total of all files, and an empty file is reported by
    save_upload as not_pdf.
    """
    if error.code == TOO_LARGE:
        limit_mb = max_total_bytes // _MEGABYTE
        message = (
            f"These files are larger than {limit_mb} MB in total. "
            "Please choose fewer or smaller files."
            if limit_mb >= 1
            else None
        )
        return AppError(TOO_LARGE, message)
    if error.code == NOT_PDF:
        return AppError(
            NOT_PDF,
            f"File {position} is empty. Please choose PDFs that have pages in them.",
        )
    return error


async def _save_files(
    files: list[UploadFile], upload_dir: Path, max_total_bytes: int
) -> tuple[list[Path], int]:
    """Stream every file to the upload folder, in order, and check it looks like a PDF.

    max_total_bytes caps the sum of all files. A file that does not look like a
    PDF by its signature is rejected immediately, naming its position.
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
        if not looks_like_pdf(destination):
            raise AppError(
                NOT_PDF,
                f"File {position} doesn't look like a PDF. Please choose PDFs and try again.",
            )
        saved.append(destination)
    return saved, total


@router.post("/merge", response_model=MergeResponse)
async def merge(
    files: Annotated[list[UploadFile], File()],
) -> MergeResponse:
    """Combine two or more PDFs into one, in the order they were sent."""
    settings = get_settings()
    if len(files) < 2:
        raise AppError(
            INVALID_REQUEST,
            "Please choose at least two PDFs to merge.",
        )
    if len(files) > settings.max_merge_files:
        raise AppError(
            TOO_MANY_FILES,
            f"You chose {len(files)} files, and the limit is "
            f"{settings.max_merge_files}. Please choose fewer files and try again.",
        )

    job_id = new_job_id()
    upload_dir = get_upload_dir(job_id, create=True)
    output_dir = get_output_dir(job_id, create=True)
    succeeded = False
    try:
        saved_paths, total_input_size = await _save_files(
            files, upload_dir, settings.max_upload_mb * _MEGABYTE
        )

        result = await run_in_threadpool(merge_pdfs, saved_paths, output_dir)

        write_meta(
            job_id,
            {
                "result_name": result.result_name,
                "download_name": DOWNLOAD_NAME,
                "file_count": result.file_count,
                "page_count": result.page_count,
                "total_input_size": total_input_size,
                "result_size": result.result_size,
            },
        )
        response = MergeResponse(
            job_id=job_id,
            file_count=result.file_count,
            page_count=result.page_count,
            total_input_size=total_input_size,
            result_size=result.result_size,
            download_name=DOWNLOAD_NAME,
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

