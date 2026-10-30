"""One error shape for the whole API.

Every error response is {"error": {"code": "...", "message": "..."}}, and the
message is a friendly sentence meant for end users. Raise AppError anywhere;
register_error_handlers(app) turns it, validation errors and unexpected
exceptions into that shape. Responses never contain stack traces or file paths.
"""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.config import get_settings

# Error codes
NOT_PDF = "not_pdf"
ENCRYPTED = "encrypted"
CORRUPT = "corrupt"
TOO_LARGE = "too_large"
INVALID_LEVEL = "invalid_level"
INVALID_REQUEST = "invalid_request"
JOB_NOT_FOUND = "job_not_found"
PROCESSING_FAILED = "processing_failed"
INTERNAL_ERROR = "internal_error"

# Phase 2 error codes
NOT_IMAGE = "not_image"
TOO_MANY_FILES = "too_many_files"
TOO_MANY_PAGES = "too_many_pages"
INVALID_QUALITY = "invalid_quality"
INVALID_PAGE_SIZE = "invalid_page_size"

# HTTP status for each code
ERROR_STATUS: dict[str, int] = {
    NOT_PDF: 400,
    ENCRYPTED: 400,
    CORRUPT: 400,
    TOO_LARGE: 413,
    INVALID_LEVEL: 422,
    INVALID_REQUEST: 422,
    JOB_NOT_FOUND: 404,
    PROCESSING_FAILED: 500,
    INTERNAL_ERROR: 500,
    NOT_IMAGE: 400,
    TOO_MANY_FILES: 413,
    TOO_MANY_PAGES: 413,
    INVALID_QUALITY: 422,
    INVALID_PAGE_SIZE: 422,
}

# Default friendly message for each code
ERROR_MESSAGES: dict[str, str] = {
    NOT_PDF: "That file doesn't look like a PDF. Please choose a PDF and try again.",
    ENCRYPTED: "This PDF is password-protected. Please remove the password and try again.",
    CORRUPT: "We couldn't read this PDF. The file may be damaged, so please try another copy.",
    TOO_LARGE: "That file is too large. Please choose a smaller PDF.",
    INVALID_LEVEL: "Please choose a compression level: light, balanced or strong.",
    INVALID_REQUEST: "We couldn't understand that request. Please check it and try again.",
    JOB_NOT_FOUND: "We couldn't find that file. It may have expired or already been downloaded.",
    PROCESSING_FAILED: "Something went wrong while compressing your PDF. Please try again.",
    INTERNAL_ERROR: "Something went wrong on our side. Please try again in a moment.",
    NOT_IMAGE: "That file doesn't look like a JPG or PNG image. Please choose JPG or PNG images and try again.",
    TOO_MANY_FILES: "That's too many images at once. Please choose fewer images and try again.",
    TOO_MANY_PAGES: "This PDF has too many pages to convert at once. Please split it into smaller parts and try again.",
    INVALID_QUALITY: "Please choose an image quality: low, medium or high.",
    INVALID_PAGE_SIZE: "Please choose a page size: fit or A4.",
}


class AppError(Exception):
    """An error with a code, a friendly message and an HTTP status.

    Only `code` is required: the message and status default to the tables above.
    """

    def __init__(
        self,
        code: str,
        message: str | None = None,
        status_code: int | None = None,
    ) -> None:
        self.code = code
        self.message = message or ERROR_MESSAGES.get(code, ERROR_MESSAGES[INTERNAL_ERROR])
        self.status_code = status_code or ERROR_STATUS.get(code, 500)
        super().__init__(self.message)


def _error_response(
    code: str,
    message: str,
    status_code: int,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message}},
        headers=headers,
    )


def _cors_headers(request: Request) -> dict[str, str]:
    # Starlette runs the catch-all handler outside CORSMiddleware, so without
    # this the browser would hide the friendly message behind a CORS failure.
    origin = request.headers.get("origin")
    if origin and origin == get_settings().frontend_origin:
        return {"Access-Control-Allow-Origin": origin, "Vary": "Origin"}
    return {}


async def _handle_app_error(request: Request, exc: AppError) -> JSONResponse:
    return _error_response(exc.code, exc.message, exc.status_code)


async def _handle_validation_error(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    # The details FastAPI collected are deliberately not echoed back.
    return _error_response(
        INVALID_REQUEST,
        ERROR_MESSAGES[INVALID_REQUEST],
        ERROR_STATUS[INVALID_REQUEST],
    )


async def _handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    return _error_response(
        INTERNAL_ERROR,
        ERROR_MESSAGES[INTERNAL_ERROR],
        ERROR_STATUS[INTERNAL_ERROR],
        headers=_cors_headers(request),
    )


def register_error_handlers(app: FastAPI) -> None:
    """Attach the three handlers that produce the shared error shape."""
    app.add_exception_handler(AppError, _handle_app_error)
    app.add_exception_handler(RequestValidationError, _handle_validation_error)
    app.add_exception_handler(Exception, _handle_unexpected_error)