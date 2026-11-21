"""pdf-to-markdown upload endpoint."""

from typing import Annotated

from fastapi import APIRouter, File, Form, Response, UploadFile
from starlette.concurrency import run_in_threadpool

from app.api.pdf_job import pdf_job
from app.schemas.jobs import MarkdownResponse
from app.services.pdf_to_markdown import convert_pdf_to_markdown

router = APIRouter()


@router.post("/pdf-to-markdown")
async def convert(
    response: Response,
    file: Annotated[UploadFile, File()],
    include_page_markers: Annotated[bool, Form()] = True,
) -> MarkdownResponse:
    async with pdf_job(file, ".md") as job:
        pages, words, tokens, markdown = await run_in_threadpool(
            convert_pdf_to_markdown, job.source, job.target, include_page_markers
        )
        response.headers["X-Page-Count"] = str(pages)
        response.headers["X-Word-Count"] = str(words)
        response.headers["X-Estimated-Tokens"] = str(tokens)
        return MarkdownResponse(
            job_id=job.job_id,
            download_name=job.download_name,
            download_url=job.download_url,
            page_count=pages,
            word_count=words,
            estimated_tokens=tokens,
            markdown=markdown,
        )
