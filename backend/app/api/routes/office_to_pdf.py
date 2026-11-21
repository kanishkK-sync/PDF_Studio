"""Office document to PDF upload routes."""

import zipfile
from typing import Annotated

from fastapi import APIRouter, File, UploadFile
from starlette.concurrency import run_in_threadpool

from app.core.config import get_settings
from app.core.errors import AppError
from app.schemas.jobs import OfficeToPdfResponse
from app.services.office_to_pdf import OfficeKind, convert_office_to_pdf
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
_SUFFIX = {"word": ".docx", "powerpoint": ".pptx", "excel": ".xlsx"}
_REQUIRED_PART = {
    "word": "word/document.xml",
    "powerpoint": "ppt/presentation.xml",
    "excel": "xl/workbook.xml",
}


async def _convert(file: UploadFile, kind: OfficeKind) -> OfficeToPdfResponse:
    job_id = new_job_id()
    upload_dir = get_upload_dir(job_id, create=True)
    output_dir = get_output_dir(job_id, create=True)
    succeeded = False
    try:
        path = upload_dir / ("input" + _SUFFIX[kind])
        original_size = await save_upload(
            file, path, get_settings().max_upload_mb * 1024 * 1024
        )
        if not zipfile.is_zipfile(path):
            raise AppError("not_office")
        try:
            with zipfile.ZipFile(path) as archive:
                if _REQUIRED_PART[kind] not in archive.namelist():
                    raise AppError("not_office")
        except zipfile.BadZipFile as exc:
            raise AppError("not_office") from exc
        result = await run_in_threadpool(convert_office_to_pdf, path, output_dir, kind)
        name = safe_display_name(file.filename)
        download_name = f"{name}.pdf"
        write_meta(
            job_id,
            {
                "result_name": result.result_name,
                "download_name": download_name,
                "original_name": name,
                "original_size": original_size,
                "result_size": result.result_size,
                "page_count": result.page_count,
            },
        )
        response = OfficeToPdfResponse(
            job_id=job_id,
            original_name=name,
            original_size=original_size,
            result_size=result.result_size,
            page_count=result.page_count,
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


@router.post("/word-to-pdf", response_model=OfficeToPdfResponse)
async def word_to_pdf(file: Annotated[UploadFile, File()]) -> OfficeToPdfResponse:
    return await _convert(file, "word")


@router.post("/powerpoint-to-pdf", response_model=OfficeToPdfResponse)
async def powerpoint_to_pdf(file: Annotated[UploadFile, File()]) -> OfficeToPdfResponse:
    return await _convert(file, "powerpoint")


@router.post("/excel-to-pdf", response_model=OfficeToPdfResponse)
async def excel_to_pdf(file: Annotated[UploadFile, File()]) -> OfficeToPdfResponse:
    return await _convert(file, "excel")
