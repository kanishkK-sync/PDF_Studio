"""POST /api/pdf-to-jpg: upload a PDF, render its pages as JPEGs, return the job."""

import gc
import shutil
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, File, Form, UploadFile
from starlette.concurrency import run_in_threadpool

from app.core.config import get_settings
from app.core.errors import NOT_PDF, AppError
from app.schemas.jobs import PdfToJpgResponse
from app.services.pdf_to_jpg import convert_pdf_to_jpg, parse_quality
from app.utils.storage import (
    delete_job,
    get_output_dir,
    get_upload_dir,
    new_job_id,
    write_meta,
)
from app.utils.uploads import looks_like_pdf, safe_display_name, save_upload

router = APIRouter()

INPUT_NAME = "input.pdf"
_MEGABYTE = 1024 * 1024


def _remove_folder(path: Path) -> None:
    """Remove a folder, retrying once after a garbage collection.

    On Windows a file that is still open cannot be deleted. A PyMuPDF object
    that is no longer referenced but not yet freed can be the holder, so
    collecting garbage and trying again usually clears it. Whatever still
    survives is left for the sweeper. (Same helper as routes/compress.py,
    copied because that file is not to be touched.)
    """
    shutil.rmtree(path, ignore_errors=True)
    if path.exists():
        gc.collect()
        shutil.rmtree(path, ignore_errors=True)


@router.post("/pdf-to-jpg", response_model=PdfToJpgResponse)
async def convert(
    file: Annotated[UploadFile, File()],
    quality: Annotated[str | None, Form()] = None,
) -> PdfToJpgResponse:
    """Convert an uploaded PDF to JPG images at the requested quality.

    The upload folder is removed on every path; the output folder is removed on
    every failure, so a failed job leaves nothing behind.
    """
    chosen_quality = parse_quality(quality)
    settings = get_settings()

    job_id = new_job_id()
    upload_dir = get_upload_dir(job_id, create=True)
    output_dir = get_output_dir(job_id, create=True)
    succeeded = False
    try:
        input_path = upload_dir / INPUT_NAME
        await save_upload(file, input_path, settings.max_upload_mb * _MEGABYTE)
        if not looks_like_pdf(input_path):
            raise AppError(NOT_PDF)

        result = await run_in_threadpool(
            convert_pdf_to_jpg, input_path, output_dir, chosen_quality
        )

        original_name = safe_display_name(file.filename)
        download_name = (
            f"{original_name}.jpg"
            if result.kind == "jpg"
            else f"{original_name}-jpg.zip"
        )
        write_meta(
            job_id,
            {
                "original_name": original_name,
                "result_name": result.result_name,
                "download_name": download_name,
                "quality": chosen_quality,
                "kind": result.kind,
                "page_count": result.page_count,
                "file_count": result.file_count,
                "result_size": result.result_size,
            },
        )
        response = PdfToJpgResponse(
            job_id=job_id,
            original_name=original_name,
            page_count=result.page_count,
            file_count=result.file_count,
            result_size=result.result_size,
            kind=result.kind,
            quality=chosen_quality,
            download_url=f"/api/jobs/{job_id}/download",
        )
        succeeded = True
        return response
    finally:
        await file.close()
        _remove_folder(upload_dir)
        if not succeeded:
            delete_job(job_id)