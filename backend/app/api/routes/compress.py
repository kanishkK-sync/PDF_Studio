"""POST /api/compress: upload a PDF, compress it, return the job description."""

import gc
import shutil
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, File, Form, UploadFile
from starlette.concurrency import run_in_threadpool

from app.core.config import get_settings
from app.core.errors import NOT_PDF, AppError
from app.schemas.jobs import CompressResponse
from app.services.compress import RESULT_NAME, compress_pdf, parse_level
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
    survives is left for the sweeper.
    """
    shutil.rmtree(path, ignore_errors=True)
    if path.exists():
        gc.collect()
        shutil.rmtree(path, ignore_errors=True)


@router.post("/compress", response_model=CompressResponse)
async def compress(
    file: Annotated[UploadFile, File()],
    level: Annotated[str | None, Form()] = None,
) -> CompressResponse:
    """Compress an uploaded PDF at the requested level.

    The upload folder is removed on every path; the output folder is removed on
    every failure, so a failed job leaves nothing behind.
    """
    chosen_level = parse_level(level)
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
            compress_pdf, input_path, output_dir / RESULT_NAME, chosen_level
        )

        original_name = safe_display_name(file.filename)
        saved_bytes = max(0, result.original_size - result.compressed_size)
        saved_percent = (
            round(saved_bytes / result.original_size * 100, 1)
            if result.original_size > 0
            else 0.0
        )
        write_meta(
            job_id,
            {
                "original_name": original_name,
                "level": chosen_level,
                "original_size": result.original_size,
                "compressed_size": result.compressed_size,
                "already_optimized": result.already_optimized,
            },
        )
        response = CompressResponse(
            job_id=job_id,
            original_name=original_name,
            original_size=result.original_size,
            compressed_size=result.compressed_size,
            saved_bytes=saved_bytes,
            saved_percent=saved_percent,
            already_optimized=result.already_optimized,
            level=chosen_level,
            download_url=f"/api/jobs/{job_id}/download",
        )
        succeeded = True
        return response
    finally:
        await file.close()
        _remove_folder(upload_dir)
        if not succeeded:
            delete_job(job_id)