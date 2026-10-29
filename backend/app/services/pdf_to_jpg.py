"""PDF to JPG engine.

One job renders every page of a PDF to a JPEG, one page at a time so memory
stays flat however long the document is:

* a single page is written as result.jpg;
* several pages are written as result.zip (ZIP_STORED, because JPEG data does
  not compress), with generated entry names page-001.jpg, page-002.jpg, ...

Client file names are never used. A page that cannot be rendered fails the
whole job, because a silently missing page would be worse than an error.
Only logs (server side) say why something failed; AppError messages stay
friendly and free of paths or exception text.
"""

import io
import logging
import math
import os
import shutil
import tempfile
import threading
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, get_args

import pymupdf
from PIL import Image

from app.core.config import get_settings
from app.core.errors import (
    CORRUPT,
    ENCRYPTED,
    INVALID_QUALITY,
    PROCESSING_FAILED,
    TOO_MANY_PAGES,
    AppError,
)
from app.schemas.jobs import Quality

logger = logging.getLogger(__name__)

RESULT_JPG = "result.jpg"
RESULT_ZIP = "result.zip"

ResultKind = Literal["jpg", "zip"]

_WORK_PREFIX = ".work-"
_MIN_NAME_DIGITS = 3
_JPEG_MAGIC = b"\xff\xd8\xff"
_MAX_SIDE_PIXELS = 65_000  # a JPEG cannot be larger than 65535 pixels on a side
_FAILED_MESSAGE = "Something went wrong while converting your PDF. Please try again."


@dataclass(frozen=True)
class PdfToJpgResult:
    """What the caller needs to build a response and the job metadata."""

    page_count: int
    file_count: int
    result_size: int
    kind: ResultKind
    result_name: str


@dataclass(frozen=True)
class _Preset:
    dpi: int
    jpeg_quality: int


_PRESETS: dict[str, _Preset] = {
    "low": _Preset(dpi=100, jpeg_quality=70),
    "medium": _Preset(dpi=150, jpeg_quality=85),
    "high": _Preset(dpi=220, jpeg_quality=92),
}


# -- Concurrency ---------------------------------------------------------------

# Each engine owns its gate, so the limit is MAX_CONCURRENT_JOBS per tool, not
# a single limit across tools (compress.py keeps its own and is not touched).
_gate_lock = threading.Lock()
_gate: threading.BoundedSemaphore | None = None


def rebuild_concurrency_gate() -> None:
    """Recreate the gate from the current settings.

    Needed because server start and tests change max_concurrent_jobs after the
    module was imported. Jobs already running keep releasing the old gate.
    """
    global _gate
    with _gate_lock:
        _gate = threading.BoundedSemaphore(get_settings().max_concurrent_jobs)


def _get_gate() -> threading.BoundedSemaphore:
    global _gate
    with _gate_lock:
        if _gate is None:
            _gate = threading.BoundedSemaphore(get_settings().max_concurrent_jobs)
        return _gate


# -- Public API ----------------------------------------------------------------


def parse_quality(raw: object) -> Quality:
    """Return the quality if `raw` is exactly low, medium or high.

    Raises invalid_quality for anything else, including None.
    """
    for quality in get_args(Quality):
        if raw == quality:
            return quality
    raise AppError(INVALID_QUALITY)


def convert_pdf_to_jpg(
    input_path: Path, output_dir: Path, quality: Quality
) -> PdfToJpgResult:
    """Render `input_path` into result.jpg or result.zip inside `output_dir`.

    Blocking and CPU heavy: call it from a worker thread. The concurrency gate
    is acquired here, inside that thread, so waiting jobs never block the event
    loop. Every failure leaves as an AppError.
    """
    parse_quality(quality)
    gate = _get_gate()
    gate.acquire()
    try:
        return _convert_locked(input_path, output_dir, quality)
    except AppError:
        raise
    except Exception as exc:
        # PyMuPDF and Pillow raise many unrelated types; the client only needs
        # to know that processing failed.
        logger.exception("PDF to JPG failed unexpectedly")
        raise AppError(PROCESSING_FAILED, _FAILED_MESSAGE) from exc
    finally:
        gate.release()


# -- Orchestration -------------------------------------------------------------


def _open_document(path: Path) -> pymupdf.Document:
    """Open the input and classify it. The caller must close the result.

    AppError is raised only after the except blocks have ended. An exception
    raised from inside one would carry a traceback that keeps PyMuPDF's
    half-built Document alive, and on Windows that can leave the uploaded file
    open so the job folder cannot be deleted.
    """
    document: pymupdf.Document | None = None
    try:
        document = pymupdf.open(str(path))
    except Exception as exc:  # noqa: BLE001 - PyMuPDF raises several unrelated types here
        logger.info("Input could not be opened: %s", exc)
    if document is None:
        raise AppError(CORRUPT)

    problem: str | None = None
    try:
        if document.needs_pass or document.is_encrypted:
            problem = ENCRYPTED
        elif not document.is_pdf or document.page_count < 1:
            problem = CORRUPT
    except Exception as exc:  # noqa: BLE001 - any failure to read the basics means a damaged file
        logger.info("Input could not be read: %s", exc)
        problem = CORRUPT
    if problem is not None:
        document.close()
        raise AppError(problem)
    return document


def _convert_locked(
    input_path: Path, output_dir: Path, quality: Quality
) -> PdfToJpgResult:
    settings = get_settings()
    preset = _PRESETS[quality]

    document = _open_document(input_path)
    try:
        page_count = document.page_count
        if page_count > settings.max_pdf_pages:
            raise AppError(
                TOO_MANY_PAGES,
                f"This PDF has {page_count} pages, and the limit is "
                f"{settings.max_pdf_pages}. Please split it into smaller parts "
                "and try again.",
            )

        # Inside the job's output folder so the sweeper also covers leftovers.
        work_dir = Path(tempfile.mkdtemp(prefix=_WORK_PREFIX, dir=output_dir))
        try:
            kind: ResultKind
            if page_count == 1:
                kind, name = "jpg", RESULT_JPG
                staged = work_dir / name
                staged.write_bytes(
                    _render_jpeg(document, 0, preset, settings.max_render_pixels)
                )
            else:
                kind, name = "zip", RESULT_ZIP
                staged = work_dir / name
                _write_zip(
                    document, staged, preset, settings.max_render_pixels, page_count
                )
            result_size = staged.stat().st_size
            os.replace(staged, output_dir / name)
            return PdfToJpgResult(
                page_count=page_count,
                file_count=page_count,
                result_size=result_size,
                kind=kind,
                result_name=name,
            )
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)
    finally:
        document.close()


def _write_zip(
    document: pymupdf.Document,
    destination: Path,
    preset: _Preset,
    max_pixels: int,
    page_count: int,
) -> None:
    """Render each page straight into a stored zip: one page in memory at a time."""
    digits = max(_MIN_NAME_DIGITS, len(str(page_count)))
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_STORED) as archive:
        for index in range(page_count):
            data = _render_jpeg(document, index, preset, max_pixels)
            archive.writestr(f"page-{index + 1:0{digits}d}.jpg", data)


# -- Rendering -----------------------------------------------------------------


def _pixel_size(width_pt: float, height_pt: float, dpi: int) -> tuple[int, int]:
    """An upper estimate of a rendered page in pixels (rounding can add one)."""
    return (
        math.ceil(width_pt * dpi / 72) + 1,
        math.ceil(height_pt * dpi / 72) + 1,
    )


def _fits(width_pt: float, height_pt: float, dpi: int, max_pixels: int) -> bool:
    width_px, height_px = _pixel_size(width_pt, height_pt, dpi)
    return (
        width_px * height_px <= max_pixels
        and max(width_px, height_px) <= _MAX_SIDE_PIXELS
    )


def _fit_dpi(rect: pymupdf.Rect, wanted: int, max_pixels: int) -> int:
    """The DPI to render at: the wanted one, lowered for an oversized page.

    Lowering is the product rule (an oversized page must not fail), bounded by
    the pixel budget per page and by the JPEG side limit. Raises ValueError for
    a page with no usable size, which fails the job.
    """
    width_pt = float(rect.width)
    height_pt = float(rect.height)
    if (
        not math.isfinite(width_pt)
        or not math.isfinite(height_pt)
        or width_pt <= 0
        or height_pt <= 0
    ):
        raise ValueError("page has no usable size")
    if _fits(width_pt, height_pt, wanted, max_pixels):
        return wanted

    area_square_inches = (width_pt / 72) * (height_pt / 72)
    limit = min(
        float(wanted),
        math.sqrt(max_pixels / area_square_inches),
        _MAX_SIDE_PIXELS * 72 / max(width_pt, height_pt),
    )
    dpi = max(1, int(limit))
    while dpi > 1 and not _fits(width_pt, height_pt, dpi, max_pixels):
        dpi -= 1
    if not _fits(width_pt, height_pt, dpi, max_pixels):
        raise ValueError("page is too large to render")
    return dpi


def _pixmap_jpeg(pixmap: pymupdf.Pixmap, quality: int) -> bytes:
    """JPEG bytes from PyMuPDF itself (no extra copy of the pixels)."""
    return pixmap.tobytes(output="jpeg", jpg_quality=quality)


def _pillow_jpeg(pixmap: pymupdf.Pixmap, quality: int) -> bytes:
    """JPEG bytes through Pillow, for a PyMuPDF without JPEG output."""
    if pixmap.alpha or pixmap.n not in (1, 3):
        raise ValueError("unexpected pixmap layout")
    mode = "L" if pixmap.n == 1 else "RGB"
    image = Image.frombuffer(
        mode, (pixmap.width, pixmap.height), pixmap.samples, "raw", mode, pixmap.stride, 1
    )
    try:
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=quality, optimize=True)
        return buffer.getvalue()
    finally:
        image.close()


def _encode_jpeg(pixmap: pymupdf.Pixmap, quality: int) -> bytes:
    """Prefer PyMuPDF's JPEG output; fall back to Pillow if it is unavailable."""
    try:
        data = _pixmap_jpeg(pixmap, quality)
    except (AttributeError, TypeError, ValueError, RuntimeError) as exc:
        logger.info("Pixmap JPEG output unavailable (%s); using Pillow", type(exc).__name__)
    else:
        if data.startswith(_JPEG_MAGIC):
            return data
        logger.info("Pixmap JPEG output was not a JPEG; using Pillow")
    return _pillow_jpeg(pixmap, quality)


def _render_jpeg(
    document: pymupdf.Document, index: int, preset: _Preset, max_pixels: int
) -> bytes:
    """Render one page to JPEG bytes, on a white background.

    The pixmap lives only inside this frame, so it is released as soon as the
    bytes exist and no more than one page is ever held. Any failure fails the
    job: a page is never skipped.
    """
    try:
        page = document.load_page(index)
        dpi = _fit_dpi(page.rect, preset.dpi, max_pixels)
        pixmap = page.get_pixmap(dpi=dpi, alpha=False)
        return _encode_jpeg(pixmap, preset.jpeg_quality)
    except AppError:
        raise
    except Exception as exc:
        logger.exception("Page %s could not be rendered", index + 1)
        raise AppError(PROCESSING_FAILED, _FAILED_MESSAGE) from exc