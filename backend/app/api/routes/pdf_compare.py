"""Compare two local uploads and publish one verified-complete ZIP job."""

from typing import Annotated

from fastapi import APIRouter, File, Response, UploadFile
from starlette.concurrency import run_in_threadpool

from app.api.pdf_job import pdf_job
from app.core.config import get_settings
from app.core.errors import NOT_PDF, TOO_LARGE, AppError
from app.schemas.jobs import CompareResponse
from app.services.pdf_compare import compare_pdfs
from app.utils.uploads import looks_like_pdf, save_upload

router = APIRouter()


@router.post("/compare-pdf")
async def compare(
    response: Response,
    original: Annotated[UploadFile, File()],
    revised: Annotated[UploadFile, File()],
) -> CompareResponse:
    try:
        async with pdf_job(original, "-comparison.zip") as job:
            second = job.source.with_name("revised.pdf")
            limit = get_settings().max_upload_mb
            try:
                await save_upload(
                    revised, second, limit * 1024**2 - job.source.stat().st_size
                )
            except AppError as exc:
                if exc.code == TOO_LARGE:
                    raise AppError(
                        TOO_LARGE, f"The two PDFs together exceed {limit} MB."
                    ) from exc
                raise
            if not looks_like_pdf(second):
                raise AppError(NOT_PDF, "The revised file does not look like a PDF.")
            stats = await run_in_threadpool(
                compare_pdfs, job.source, second, job.target
            )
            response.headers.update(
                {
                    "X-Compared-Pages": str(stats.compared_pages),
                    "X-Truncated": str(stats.truncated).lower(),
                    "X-Pages-Changed": str(stats.pages_changed),
                    "X-Total-Pages": str(stats.total_pages),
                    "X-Overall-Similarity": str(stats.overall_similarity),
                }
            )
            return CompareResponse(
                **stats.model_dump(),
                job_id=job.job_id,
                download_name=job.download_name,
                download_url=job.download_url,
            )
    finally:
        await revised.close()
