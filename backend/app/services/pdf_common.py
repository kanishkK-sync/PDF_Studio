"""PDF input guards and the process-wide PyMuPDF execution gate."""

import logging
import math
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pymupdf

from app.core.errors import CORRUPT, ENCRYPTED, PAGE_TOO_LARGE, AppError

logger = logging.getLogger(__name__)


class ConcurrencyGate:
    """Serialize PyMuPDF jobs across every endpoint in this Python process."""

    _execution_lock = threading.Lock()

    def rebuild(self) -> None:
        """Compatibility hook; the live lock must never be replaced."""

    @contextmanager
    def hold(self) -> Iterator[None]:
        """Wait in the worker thread and always release after closing files."""
        with self._execution_lock:
            yield


GLOBAL_GATE = ConcurrencyGate()


def open_pdf_document(path: Path) -> pymupdf.Document:
    """Open the input and classify it. The caller must close the result.

    Encrypted gives `encrypted`; unreadable, not a PDF or zero pages gives
    `corrupt`. AppError is raised only after the except blocks have ended. An
    exception raised from inside one would carry a traceback that keeps
    PyMuPDF's half-built Document alive, and on Windows that can leave the
    uploaded file open so the job folder cannot be deleted.
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


_MAX_SIDE_PIXELS = 65_000


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


def fit_render_dpi(rect: pymupdf.Rect, wanted: int, max_pixels: int) -> int:
    """Choose a DPI within both the pixel budget and the maximum side length."""
    width_pt = float(rect.width)
    height_pt = float(rect.height)
    if (
        not math.isfinite(width_pt)
        or not math.isfinite(height_pt)
        or width_pt <= 0
        or height_pt <= 0
    ):
        raise AppError(PAGE_TOO_LARGE)
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
        raise AppError(PAGE_TOO_LARGE)
    return dpi
