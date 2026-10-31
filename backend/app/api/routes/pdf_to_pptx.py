"""POST /api/pdf-to-pptx: upload a PDF, convert it to PowerPoint, return the job."""

from typing import Annotated

from fastapi import APIRouter, File, Form, UploadFile
from starlette.concurrency import run_in_threadpool

from app.core.config import get_settings
from app.core.errors import NOT_PDF, AppError
from app.schemas.jobs import PdfToPptxResponse
from app.services.pdf_to_pptx import convert_pdf_to_pptx, parse_mode
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


@router.post("/pdf-to-pptx", response_model=PdfToPptxResponse)
async def convert(
    file: Annotated[UploadFile, File()],
    mode: Annotated[str | None, Form()] = None,
) -> PdfToPptxResponse:
    """Convert an uploaded PDF to a PowerPoint presentation.

    The mode is checked before anything is created, so a bad or missing mode
    leaves no job and no files. After that, the upload folder is removed on
    every path and the output folder on every failure.
    """
    chosen_mode = parse_mode(mode)
    settings = get_settings()

    job_id = new_job_id()
    upload_dir = get_upload_dir(job_id, create=True)
    output_dir = get_output_dir(job_id, create=True)
    succeeded = False
    try:
        input_path = upload_dir / INPUT_NAME
        original_size = await save_upload(
            file, input_path, settings.max_upload_mb * _MEGABYTE
        )
        if not looks_like_pdf(input_path):
            raise AppError(NOT_PDF)

        result = await run_in_threadpool(
            convert_pdf_to_pptx, input_path, output_dir, chosen_mode
        )

        original_name = safe_display_name(file.filename)
        download_name = f"{original_name}.pptx"
        write_meta(
            job_id,
            {
                "original_name": original_name,
                "result_name": result.result_name,
                "download_name": download_name,
                "mode": result.mode,
                "page_count": result.page_count,
                "slide_count": result.slide_count,
                "original_size": original_size,
                "result_size": result.result_size,
            },
        )
        response = PdfToPptxResponse(
            job_id=job_id,
            original_name=original_name,
            page_count=result.page_count,
            slide_count=result.slide_count,
            mode=result.mode,
            original_size=original_size,
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