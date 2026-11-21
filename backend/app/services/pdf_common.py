"""PDF input guards and the process-wide PyMuPDF execution gate."""

import logging
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pymupdf

from app.core.errors import CORRUPT, ENCRYPTED, AppError

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
