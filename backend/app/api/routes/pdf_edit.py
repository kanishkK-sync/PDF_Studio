"""POST /api/edit-pdf: replace searchable PDF text."""

from typing import Annotated

from fastapi import APIRouter, File, Form, UploadFile
from starlette.concurrency import run_in_threadpool

from app.core.config import get_settings
from app.core.errors import INVALID_REQUEST, NOT_PDF, AppError
from app.schemas.jobs import EditPdfResponse
from app.services.pdf_edit import edit_pdf
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


@router.post("/edit-pdf", response_model=EditPdfResponse)
async def replace_text(
    file: Annotated[UploadFile, File()],
    find: Annotated[str, Form()],
    replace: Annotated[str, Form()],
) -> EditPdfResponse:
    if not find.strip() or not replace.strip() or len(find) > 500 or len(replace) > 500:
        raise AppError(
            INVALID_REQUEST,
            "Enter text to find and replacement text, each under 500 characters.",
        )
    job_id = new_job_id()
    upload_dir = get_upload_dir(job_id, create=True)
    output_dir = get_output_dir(job_id, create=True)
    succeeded = False
    try:
        input_path = upload_dir / "input.pdf"
        original_size = await save_upload(
            file, input_path, get_settings().max_upload_mb * 1024 * 1024
        )
        if not looks_like_pdf(input_path):
            raise AppError(NOT_PDF)
        result = await run_in_threadpool(edit_pdf, input_path, output_dir, find, replace)
        name = safe_display_name(file.filename)
        download_name = f"{name}-edited.pdf"
        write_meta(
            job_id,
            {"result_name": result.result_name, "download_name": download_name},
        )
        response = EditPdfResponse(
            job_id=job_id,
            original_name=name,
            original_size=original_size,
            result_size=result.result_size,
            page_count=result.page_count,
            replacement_count=result.replacement_count,
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
