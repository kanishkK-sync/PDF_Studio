"""PDF to Word engine.

One job turns one PDF into one .docx with pdf2docx, which rebuilds paragraphs,
tables and pictures from the PDF's layout. It cannot read scanned pages: they
come through as pictures, because there is no text recognition. The result is
checked before it is handed back: it must exist and be a real Word package.

Only logs (server side) say why something failed; AppError messages stay
friendly and free of paths or exception text.
"""

import importlib
import logging
import os
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

from app.core.config import get_settings
from app.core.errors import PROCESSING_FAILED, TOO_MANY_PAGES, AppError
from app.services.pdf_common import ConcurrencyGate, open_pdf_document

logger = logging.getLogger(__name__)

RESULT_DOCX = "result.docx"

_WORK_PREFIX = ".work-"
_DOCX_MAIN_PART = "word/document.xml"
_FAILED_MESSAGE = (
    "Something went wrong while converting your PDF to Word. Please try again."
)

_gate = ConcurrencyGate()
rebuild_concurrency_gate = _gate.rebuild


@dataclass(frozen=True)
class PdfToWordResult:
    """What the caller needs to build a response and the job metadata."""

    page_count: int
    result_size: int
    result_name: str


def convert_pdf_to_word(input_path: Path, output_dir: Path) -> PdfToWordResult:
    """Build result.docx inside `output_dir` from the PDF at `input_path`.

    Blocking and CPU heavy: call it from a worker thread. The concurrency slot
    is taken here, inside that thread. Every failure leaves as an AppError.
    """
    try:
        with _gate.hold():
            return _convert_locked(input_path, output_dir)
    except AppError:
        raise
    except Exception as exc:
        # pdf2docx, PyMuPDF and zipfile raise many unrelated types; the client
        # only needs to know that processing failed.
        logger.exception("PDF to Word failed unexpectedly")
        raise AppError(PROCESSING_FAILED, _FAILED_MESSAGE) from exc


def _convert_locked(input_path: Path, output_dir: Path) -> PdfToWordResult:
    settings = get_settings()

    document = open_pdf_document(input_path)
    try:
        page_count = document.page_count
    finally:
        # Closed before pdf2docx opens the same file again.
        document.close()
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
        staged = work_dir / RESULT_DOCX
        _run_pdf2docx(input_path, staged)
        _check_docx(staged)
        result_size = staged.stat().st_size
        os.replace(staged, output_dir / RESULT_DOCX)
        return PdfToWordResult(
            page_count=page_count,
            result_size=result_size,
            result_name=RESULT_DOCX,
        )
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def _run_pdf2docx(source: Path, destination: Path) -> None:
    """Convert every page. The converter is always closed so Windows can delete.

    pdf2docx is imported here, not at the top of the module: if the package
    were ever broken, only this tool would fail instead of the whole server.
    """
    module = importlib.import_module("pdf2docx")
    converter = module.Converter(str(source))
    try:
        converter.convert(str(destination))
    finally:
        converter.close()


def _check_docx(path: Path) -> None:
    """Raise ValueError unless `path` is a non-empty Word package."""
    if not path.is_file() or path.stat().st_size == 0:
        raise ValueError("converter produced no output")
    with zipfile.ZipFile(path) as archive:
        if _DOCX_MAIN_PART not in archive.namelist():
            raise ValueError("output is not a Word document")