"""Merge PDF engine.

Combines multiple PDF files into one PDF document using PyMuPDF. Source files
are processed one at a time and their pages, links, and annotations are merged in
the given order. Bookmarks (table of contents) from each source are preserved with
adjusted page numbers when possible.

Document metadata is not preserved; interactive form fields and some
annotations may not survive.
"""

import logging
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

import pymupdf

from app.core.config import get_settings
from app.core.errors import (
    CORRUPT,
    ENCRYPTED,
    PROCESSING_FAILED,
    TOO_MANY_PAGES,
    AppError,
)
from app.services.pdf_common import GLOBAL_GATE, open_pdf_document

logger = logging.getLogger(__name__)

RESULT_PDF = "result.pdf"

_WORK_PREFIX = ".work-"
_FAILED_MESSAGE = (
    "Something went wrong while merging your PDFs. Please try again."
)

_gate = GLOBAL_GATE
rebuild_concurrency_gate = _gate.rebuild


@dataclass(frozen=True)
class PdfMergeResult:
    """Outcome of merging PDF files."""

    page_count: int
    file_count: int
    result_size: int
    result_name: str


def merge_pdfs(input_paths: list[Path], output_dir: Path) -> PdfMergeResult:
    """Combine `input_paths` into a single PDF in `output_dir`.

    Blocking and CPU heavy: call it from a worker thread. The concurrency slot
    is taken here, inside that thread. Every failure leaves as an AppError.
    """
    try:
        with _gate.hold():
            return _merge_locked(input_paths, output_dir)
    except AppError:
        raise
    except Exception as exc:
        logger.exception("Merge failed unexpectedly")
        raise AppError(PROCESSING_FAILED, _FAILED_MESSAGE) from exc


def _merge_locked(input_paths: list[Path], output_dir: Path) -> PdfMergeResult:
    settings = get_settings()
    work_dir = Path(tempfile.mkdtemp(prefix=_WORK_PREFIX, dir=output_dir))
    merged: pymupdf.Document | None = None
    all_tocs: list[list[object]] = []
    total_pages = 0

    try:
        merged = pymupdf.open()
        for position, input_path in enumerate(input_paths, start=1):
            try:
                source = open_pdf_document(input_path)
            except AppError as error:
                if error.code == ENCRYPTED:
                    raise AppError(
                        ENCRYPTED,
                        f"File {position} is password-protected. "
                        "Please remove the password and try again.",
                    ) from error
                if error.code == CORRUPT:
                    raise AppError(
                        CORRUPT,
                        f"We couldn't read file {position}. "
                        "The file may be damaged, so please try another copy.",
                    ) from error
                raise

            try:
                page_count = source.page_count
                total_pages += page_count
                if total_pages > settings.max_pdf_pages:
                    raise AppError(
                        TOO_MANY_PAGES,
                        f"The merged document would have {total_pages} pages, "
                        f"and the limit is {settings.max_pdf_pages}. "
                        "Please choose fewer files or smaller documents and try again.",
                    )

                source_toc = source.get_toc()
                for item in source_toc:
                    item[2] = int(item[2]) + merged.page_count
                all_tocs.extend(source_toc)

                merged.insert_pdf(source, links=True, annots=True)
            finally:
                source.close()

        if all_tocs:
            try:
                merged.set_toc(all_tocs)
            except Exception:
                logger.exception("Could not copy bookmarks to merged document")

        staged = work_dir / RESULT_PDF
        merged.save(str(staged), garbage=3, deflate=True)
        merged.close()

        check_doc = pymupdf.open(str(staged))
        try:
            if check_doc.page_count != total_pages:
                raise AppError(PROCESSING_FAILED, _FAILED_MESSAGE)
        finally:
            check_doc.close()

        result_size = staged.stat().st_size
        os.replace(staged, output_dir / RESULT_PDF)
        return PdfMergeResult(
            page_count=total_pages,
            file_count=len(input_paths),
            result_size=result_size,
            result_name=RESULT_PDF,
        )
    finally:
        if merged is not None and not merged.is_closed:
            merged.close()
        shutil.rmtree(work_dir, ignore_errors=True)

