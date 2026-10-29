"""Download and delete routes for finished jobs."""

import stat
from collections.abc import Mapping
from typing import Any

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

# The only files a download may serve: name -> (Content-Type, extension). meta.json
# is data on disk and is never trusted as a path or a header, so the file name
# must be exactly one of these keys and the Content-Type comes only from here.
RESULT_TYPES: Mapping[str, tuple[str, str]] = {
    "result.pdf": ("application/pdf", ".pdf"),
    "result.jpg": ("image/jpeg", ".jpg"),
    "result.zip": ("application/zip", ".zip"),
}


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


def _result_name(meta: dict[str, Any] | None) -> str:
    """The result file to serve, checked against the allowlist.

    A Phase 1 job has no "result_name" key and always means result.pdf.
    Anything else must be a string that is exactly one of the allowlisted
    names; otherwise the job is treated as not found.
    """
    if meta is None or "result_name" not in meta:
        return RESULT_NAME
    name = meta["result_name"]
    if not isinstance(name, str) or name not in RESULT_TYPES:
        raise AppError(JOB_NOT_FOUND)
    return name


def _download_filename(meta: dict[str, Any] | None, result_name: str) -> str:
    """The attachment name: sanitised stem plus the extension fixed by the type.

    The full candidate name (stem, suffix and extension) is built first and
    sanitised once, so a dot inside the stem ("report.v2") survives: the
    sanitiser only strips the final extension, which is the one we appended.
    A stored download_name wins; a Phase 1 job falls back to
    "<original_name>-compressed.pdf". The extension always comes from the
    allowlisted type, never from stored data.
    """
    extension = RESULT_TYPES[result_name][1]
    stored = meta.get("download_name") if meta else None
    if isinstance(stored, str) and stored.strip():
        candidate = stored
    else:
        original = meta.get("original_name") if meta else None
        stem = original if isinstance(original, str) and original.strip() else "document"
        suffix = "-compressed" if result_name == RESULT_NAME else ""
        candidate = f"{stem}{suffix}{extension}"
    return f"{safe_display_name(candidate)}{extension}"
    """The attachment name: sanitised stem plus the extension fixed by the type.

    A stored download_name is cleaned like any client name (no folders, no
    control characters) and its extension is replaced by the allowlisted one.
    A Phase 1 job falls back to "<original_name>-compressed.pdf".
    """
    extension = RESULT_TYPES[result_name][1]
    stored = meta.get("download_name") if meta else None
    if isinstance(stored, str) and stored.strip():
        return f"{safe_display_name(stored)}{extension}"

    original = meta.get("original_name") if meta else None
    stem = safe_display_name(original if isinstance(original, str) else None)
    suffix = "-compressed" if result_name == RESULT_NAME else ""
    return f"{stem}{suffix}{extension}"


@router.get("/jobs/{job_id}/download")
def download_result(job_id: str) -> FileResponse:
    """Stream the finished file as an attachment, then delete the job.

    Invalid ids raise job_not_found inside get_output_dir before any disk access.
    """
    output_dir = get_output_dir(job_id)
    meta = read_meta(job_id)
    result_name = _result_name(meta)

    result_path = (output_dir / result_name).resolve()
    if not result_path.is_relative_to(output_dir):
        raise AppError(JOB_NOT_FOUND)
    try:
        stat_result = result_path.stat()
    except OSError as exc:
        raise AppError(JOB_NOT_FOUND) from exc
    if not stat.S_ISREG(stat_result.st_mode):
        raise AppError(JOB_NOT_FOUND)

    return _FullFileResponse(
        result_path,
        media_type=RESULT_TYPES[result_name][0],
        filename=_download_filename(meta, result_name),
        headers={"Cache-Control": "no-store"},
        stat_result=stat_result,
        background=BackgroundTask(delete_job, job_id),
    )


@router.delete("/jobs/{job_id}", status_code=204)
def remove_job(job_id: str) -> Response:
    """Delete a job. Always 204: invalid, unknown and repeated ids are all fine."""
    delete_job(job_id)
    return Response(status_code=204)