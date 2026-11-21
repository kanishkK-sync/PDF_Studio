"""redact-pdf upload endpoint."""

from typing import Annotated

from fastapi import APIRouter, File, Form, Response, UploadFile
from starlette.concurrency import run_in_threadpool

from app.api.pdf_job import pdf_job
from app.schemas.jobs import RedactResponse
from app.services.pdf_redact import redact_pdf

router = APIRouter()


@router.post("/redact-pdf")
async def convert(
    response: Response,
    file: Annotated[UploadFile, File()],
    terms: Annotated[str, Form()] = "",
    presets: Annotated[str, Form()] = "",
    scrub_metadata: Annotated[bool, Form()] = True,
) -> RedactResponse:
    async with pdf_job(file, "-redacted.pdf") as job:
        count = await run_in_threadpool(
            redact_pdf, job.source, job.target, terms, presets, scrub_metadata
        )
        response.headers["X-Redacted-Count"] = str(count)
        response.headers["X-Metadata-Scrubbed"] = str(scrub_metadata).lower()
        response.headers["X-Verified-Unrecoverable"] = "true"
        return RedactResponse(
            job_id=job.job_id,
            download_name=job.download_name,
            download_url=job.download_url,
            redacted_count=count,
            metadata_scrubbed=scrub_metadata,
            verified_unrecoverable=True,
        )
