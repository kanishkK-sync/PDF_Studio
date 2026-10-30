"""Saving uploads to disk, checking they look like PDFs, and naming them safely."""

import os
import re
import unicodedata
from pathlib import Path

import aiofiles
from fastapi import UploadFile

from app.core.errors import NOT_PDF, TOO_LARGE, AppError

CHUNK_SIZE = 1024 * 1024  # 1 MB
MAX_NAME_LENGTH = 100
FALLBACK_NAME = "document"
EMPTY_FILE_MESSAGE = "That file is empty. Please choose a PDF that has pages in it."

_MEGABYTE = 1024 * 1024
_PDF_SIGNATURE = b"%PDF-"
_JPEG_SIGNATURE = b"\xff\xd8\xff"
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_SIGNATURE_WINDOW = 1024
_UNSAFE_NAME_CHARS = re.compile(r'[<>:"/\\|?*]')
# Control, format (such as right-to-left override), surrogate, private-use, unassigned.
_DROPPED_CATEGORIES = {"Cc", "Cf", "Cs", "Co", "Cn"}


def _too_large_message(max_bytes: int) -> str | None:
    limit_mb = max_bytes // _MEGABYTE
    if limit_mb < 1:
        return None  # not a whole number of megabytes: use the default message
    return f"That file is larger than {limit_mb} MB. Please choose a smaller PDF."


async def save_upload(upload: UploadFile, destination: Path, max_bytes: int) -> int:
    """Stream an upload to `destination` in 1 MB chunks and return its size in bytes.

    Raises too_large as soon as more than `max_bytes` have arrived, and not_pdf
    for an empty file. Whatever goes wrong, no partial file is left behind.
    """
    written = 0
    try:
        async with aiofiles.open(destination, "wb") as out:
            while chunk := await upload.read(CHUNK_SIZE):
                written += len(chunk)
                if written > max_bytes:
                    raise AppError(TOO_LARGE, _too_large_message(max_bytes))
                await out.write(chunk)
        if written == 0:
            raise AppError(NOT_PDF, EMPTY_FILE_MESSAGE)
    except BaseException:
        destination.unlink(missing_ok=True)
        raise
    return written


def looks_like_pdf(path: Path) -> bool:
    """True if %PDF- appears in the first 1024 bytes.

    Only the content is checked, never the client's filename or content type.
    """
    with path.open("rb") as file:
        head = file.read(_SIGNATURE_WINDOW)
    return _PDF_SIGNATURE in head


def _starts_with(path: Path, signature: bytes) -> bool:
    with path.open("rb") as file:
        return file.read(len(signature)) == signature


def looks_like_jpeg(path: Path) -> bool:
    """True if the file starts with the JPEG signature (FF D8 FF).

    Only the bytes are checked, never the client's filename or content type.
    """
    return _starts_with(path, _JPEG_SIGNATURE)


def looks_like_png(path: Path) -> bool:
    """True if the file starts with the 8-byte PNG signature."""
    return _starts_with(path, _PNG_SIGNATURE)


def safe_display_name(filename: str | None) -> str:
    """A safe name to show and reuse: base name only, no extension, at most 100 characters.

    Falls back to "document" when nothing usable is left.
    """
    if not filename:
        return FALLBACK_NAME

    base = filename.replace("\\", "/").rsplit("/", 1)[-1]
    stem, _extension = os.path.splitext(base)

    stem = _UNSAFE_NAME_CHARS.sub("", stem)
    stem = "".join(ch for ch in stem if unicodedata.category(ch) not in _DROPPED_CATEGORIES)
    stem = " ".join(stem.split()).strip(" .")
    stem = stem[:MAX_NAME_LENGTH].rstrip(" .")

    return stem or FALLBACK_NAME