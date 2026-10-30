"""Helpers shared by the newer PDF engines.

The older engines (compress, pdf_to_jpg) keep private copies of this logic.
New engines use this module so the copies stop growing.
"""

import logging
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pymupdf

from app.core.config import get_settings
from app.core.errors import CORRUPT, ENCRYPTED, AppError

logger = logging.getLogger(__name__)


class ConcurrencyGate:
    """A thread-based limit on how many jobs of one tool run at once.

    The limit is MAX_CONCURRENT_JOBS per tool, not across tools. The slot is
    taken inside the worker thread, so waiting jobs never block the event loop.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._semaphore: threading.BoundedSemaphore | None = None

    def rebuild(self) -> None:
        """Recreate the semaphore from the current settings.

        Needed because server start and tests change max_concurrent_jobs after
        the module was imported. Jobs already running keep releasing the old one.
        """
        with self._lock:
            self._semaphore = threading.BoundedSemaphore(
                get_settings().max_concurrent_jobs
            )

    def _current(self) -> threading.BoundedSemaphore:
        with self._lock:
            if self._semaphore is None:
                self._semaphore = threading.BoundedSemaphore(
                    get_settings().max_concurrent_jobs
                )
            return self._semaphore

    @contextmanager
    def hold(self) -> Iterator[None]:
        """Wait for a free slot, keep it for the with-block, always release it."""
        semaphore = self._current()
        semaphore.acquire()
        try:
            yield
        finally:
            semaphore.release()


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