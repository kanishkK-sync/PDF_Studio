"""POST /api/split: extract pages or separate a PDF into parts."""

from typing import Annotated

from fastapi import APIRouter, File, Form, UploadFile
from starlette.concurrency import run_in_threadpool

from app.core.config import get_settings
from app.core.errors import INVALID_REQUEST, NOT_PDF, AppError
from app.schemas.jobs import SplitMode, SplitResponse
from app.services.pdf_split import parse_ranges, split_pdf
from app.utils.cleanup import remove_folder
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
_VALID_MODES: set[str] = {"extract", "separate"}


@router.post("/split", response_model=SplitResponse)
async def split(
    file: Annotated[UploadFile, File()],
    ranges: Annotated[str, Form()],
    mode: Annotated[str, Form()],
) -> SplitResponse:
    """Split a PDF into selected pages or separate PDF files."""
    if mode not in _VALID_MODES:
        raise AppError(
            INVALID_REQUEST,
            "Please choose how to split: extract or separate.",
        )
    chosen_mode: SplitMode = "extract" if mode == "extract" else "separate"
    parsed_ranges = parse_ranges(ranges)

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
            split_pdf, input_path, output_dir, parsed_ranges, chosen_mode
        )

        original_name = safe_display_name(file.filename)
        download_name = (
            f"{original_name}-pages.pdf"
            if chosen_mode == "extract"
            else f"{original_name}-split.zip"
        )

        write_meta(
            job_id,
            {
                "original_name": original_name,
                "result_name": result.result_name,
                "download_name": download_name,
                "mode": chosen_mode,
                "page_count": result.page_count,
                "selected_pages": result.selected_pages,
                "file_count": result.file_count,
                "kind": result.kind,
                "result_size": result.result_size,
            },
        )
        response = SplitResponse(
            job_id=job_id,
            original_name=original_name,
            page_count=result.page_count,
            selected_pages=result.selected_pages,
            file_count=result.file_count,
            kind=result.kind,
            mode=chosen_mode,
            result_size=result.result_size,
            download_name=download_name,
            download_url=f"/api/jobs/{job_id}/download",
        )
        succeeded = True
        return response
    finally:
        await file.close()
        remove_folder(upload_dir)
        if not succeeded:
            delete_job(job_id)

