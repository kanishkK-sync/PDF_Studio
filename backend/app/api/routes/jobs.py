"""Download and delete routes for finished jobs."""

from fastapi import APIRouter, Response
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask
from starlette.types import Receive, Scope, Send

from app.core.errors import JOB_NOT_FOUND, AppError
from app.services.compress import RESULT_NAME
from app.utils.storage import delete_job, get_output_dir, read_meta
from app.utils.uploads import safe_display_name

router = APIRouter()

_RANGE_HEADERS = {b"range", b"if-range"}
_FALLBACK_NAME = "document"


class _FullFileResponse(FileResponse):
    """A FileResponse that always sends the whole file.

    The job is deleted after the response is sent. If a Range request were
    honoured, the 206 would also trigger the deletion and the rest of the file
    could never be fetched. So Range headers are removed before Starlette sees
    them, which gives a plain 200 with the full body every time. A HEAD (which
    FastAPI does not route here) would never delete anything either.
    """

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            if str(scope.get("method", "")).upper() == "HEAD":
                self.background = None
            headers = [
                (name, value)
                for name, value in scope["headers"]
                if name.lower() not in _RANGE_HEADERS
            ]
            scope = {**scope, "headers": headers}
        await super().__call__(scope, receive, send)


@router.get("/jobs/{job_id}/download")
def download_result(job_id: str) -> FileResponse:
    """Stream the compressed PDF as an attachment, then delete the job.

    Invalid ids raise job_not_found inside get_output_dir before any disk access.
    """
    output_dir = get_output_dir(job_id)
    result_path = output_dir / RESULT_NAME
    try:
        stat_result = result_path.stat()
    except OSError as exc:
        raise AppError(JOB_NOT_FOUND) from exc

    meta = read_meta(job_id)
    stored_name = meta.get("original_name") if meta else None
    base_name = safe_display_name(stored_name if isinstance(stored_name, str) else None)
    filename = f"{base_name or _FALLBACK_NAME}-compressed.pdf"

    return _FullFileResponse(
        result_path,
        media_type="application/pdf",
        filename=filename,
        headers={"Cache-Control": "no-store"},
        stat_result=stat_result,
        background=BackgroundTask(delete_job, job_id),
    )


@router.delete("/jobs/{job_id}", status_code=204)
def remove_job(job_id: str) -> Response:
    """Delete a job. Always 204: invalid, unknown and repeated ids are all fine."""
    delete_job(job_id)
    return Response(status_code=204)