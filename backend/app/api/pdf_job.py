"""Stage a single PDF and publish the result only after conversion succeeds."""

import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from fastapi import UploadFile

from app.core.config import get_settings
from app.core.errors import NOT_PDF, PROCESSING_FAILED, AppError
from app.utils.cleanup import remove_folder
from app.utils.storage import (
    delete_job,
    get_output_dir,
    get_upload_dir,
    new_job_id,
    write_meta,
)
from app.utils.uploads import looks_like_pdf, safe_display_name, save_upload

logger = logging.getLogger(__name__)


@dataclass
class PdfJob:
    job_id: str
    source: Path
    target: Path
    download_name: str

    @property
    def download_url(self):
        return f"/api/jobs/{self.job_id}/download"


@asynccontextmanager
async def pdf_job(file: UploadFile, suffix: str):
    job_id = new_job_id()
    folder = get_upload_dir(job_id, create=True)
    success = False
    try:
        source = folder / "input.pdf"
        await save_upload(file, source, get_settings().max_upload_mb * 1024**2)
        if not looks_like_pdf(source):
            raise AppError(NOT_PDF)
        name = safe_display_name(file.filename) + suffix
        target = get_output_dir(job_id, create=True) / ("result" + Path(name).suffix)
        staged = target.with_stem("pending")
        yield PdfJob(job_id, source, staged, name)
        write_meta(job_id, {"result_name": target.name, "download_name": name})
        staged.replace(target)
        success = True
    except AppError:
        raise
    except Exception as exc:  # noqa: BLE001 - isolate third-party document processing failures
        # Library exception messages can contain private input text.
        logger.error(
            "PDF processing failed (%s) for job %s", type(exc).__name__, job_id
        )
        raise AppError(PROCESSING_FAILED, "Could not process this PDF.") from None
    finally:
        await file.close()
        remove_folder(folder)
        if not success:
            delete_job(job_id)
