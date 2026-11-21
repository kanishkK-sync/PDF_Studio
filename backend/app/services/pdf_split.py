"""Split PDF engine.

Extracts pages or splits a PDF into parts using PyMuPDF.

Supports two modes:
- extract: combines all specified page ranges into a single PDF (result.pdf)
  in the requested order. Pages requested multiple times will appear multiple
  times.
- separate: creates a separate PDF for each range item, packaged into a ZIP archive
  (result.zip) as part-001.pdf, part-002.pdf, etc.

Bookmarks are not carried over.
"""

import logging
import os
import re
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import pymupdf

from app.core.config import get_settings
from app.core.errors import (
    INVALID_RANGES,
    PROCESSING_FAILED,
    TOO_MANY_PAGES,
    AppError,
)
from app.services.pdf_common import ConcurrencyGate, open_pdf_document

logger = logging.getLogger(__name__)

RESULT_PDF = "result.pdf"
RESULT_ZIP = "result.zip"

_WORK_PREFIX = ".work-"
_FAILED_MESSAGE = (
    "Something went wrong while splitting your PDF. Please try again."
)

_gate = ConcurrencyGate()
rebuild_concurrency_gate = _gate.rebuild

SplitMode = Literal["extract", "separate"]
SplitKind = Literal["pdf", "zip"]

_SINGLE_RE = re.compile(r"^\d{1,6}$")
_OPEN_RANGE_RE = re.compile(r"^(\d{1,6})\s*-\s*$")
_CLOSED_RANGE_RE = re.compile(r"^(\d{1,6})\s*-\s*(\d{1,6})$")


def parse_ranges(text: str) -> list[tuple[int, int | None]]:
    """Parse a range string into a list of (start, end) tuples.

    Items are comma-separated. Each item can be "N", "N-M", or "N-".
    N and M are 1-based positive integers with at most 6 digits, and N <= M.
    Must contain between 1 and 100 items. Anything invalid raises AppError(INVALID_RANGES).
    """
    stripped = text.strip()
    if not stripped:
        raise AppError(INVALID_RANGES)

    raw_items = text.split(",")
    if not (1 <= len(raw_items) <= 100):
        raise AppError(INVALID_RANGES)

    parsed: list[tuple[int, int | None]] = []
    for raw in raw_items:
        item = raw.strip()
        if not item:
            raise AppError(INVALID_RANGES)

        if _SINGLE_RE.match(item):
            num = int(item)
            if num <= 0:
                raise AppError(INVALID_RANGES)
            parsed.append((num, num))
        elif m := _CLOSED_RANGE_RE.match(item):
            start = int(m.group(1))
            end = int(m.group(2))
            if start <= 0 or end <= 0 or start > end:
                raise AppError(INVALID_RANGES)
            parsed.append((start, end))
        elif m := _OPEN_RANGE_RE.match(item):
            start = int(m.group(1))
            if start <= 0:
                raise AppError(INVALID_RANGES)
            parsed.append((start, None))
        else:
            raise AppError(INVALID_RANGES)

    return parsed


@dataclass(frozen=True)
class PdfSplitResult:
    """Outcome of splitting a PDF file."""

    page_count: int
    selected_pages: int
    file_count: int
    kind: SplitKind
    result_size: int
    result_name: str


def split_pdf(
    input_path: Path,
    output_dir: Path,
    ranges: list[tuple[int, int | None]],
    mode: SplitMode,
) -> PdfSplitResult:
    """Split or extract pages from `input_path` into `output_dir`.

    Blocking and CPU heavy: call it from a worker thread. The concurrency slot
    is taken here, inside that thread. Every failure leaves as an AppError.
    """
    try:
        with _gate.hold():
            return _split_locked(input_path, output_dir, ranges, mode)
    except AppError:
        raise
    except Exception as exc:
        logger.exception("Split failed unexpectedly")
        raise AppError(PROCESSING_FAILED, _FAILED_MESSAGE) from exc


def _split_locked(
    input_path: Path,
    output_dir: Path,
    ranges: list[tuple[int, int | None]],
    mode: SplitMode,
) -> PdfSplitResult:
    settings = get_settings()

    source = open_pdf_document(input_path)
    try:
        page_count = source.page_count
        if page_count > settings.max_pdf_pages:
            raise AppError(
                TOO_MANY_PAGES,
                f"This PDF has {page_count} pages, and the limit is "
                f"{settings.max_pdf_pages}. Please split it into smaller parts "
                "and try again.",
            )

        # Check bounds against the real page count
        for start, end in ranges:
            if start > page_count:
                raise AppError(
                    INVALID_RANGES,
                    f"This PDF has {page_count} pages, so page {start} doesn't exist.",
                )
            if end is not None and end > page_count:
                raise AppError(
                    INVALID_RANGES,
                    f"This PDF has {page_count} pages, so page {end} doesn't exist.",
                )

        work_dir = Path(tempfile.mkdtemp(prefix=_WORK_PREFIX, dir=output_dir))
        try:
            if mode == "extract":
                return _extract_mode(source, work_dir, output_dir, ranges, page_count)
            return _separate_mode(source, work_dir, output_dir, ranges, page_count)
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)
    finally:
        source.close()


def _extract_mode(
    source: pymupdf.Document,
    work_dir: Path,
    output_dir: Path,
    ranges: list[tuple[int, int | None]],
    page_count: int,
) -> PdfSplitResult:
    pages_to_extract: list[int] = []
    for start, end in ranges:
        last = page_count if end is None else end
        pages_to_extract.extend(range(start, last + 1))

    selected_pages = len(pages_to_extract)
    out_doc = pymupdf.open()
    try:
        for p in pages_to_extract:
            out_doc.insert_pdf(
                source, from_page=p - 1, to_page=p - 1, links=True, annots=True
            )

        staged = work_dir / RESULT_PDF
        out_doc.save(str(staged), garbage=3, deflate=True)
    finally:
        out_doc.close()

    check_doc = pymupdf.open(str(staged))
    try:
        if check_doc.page_count != selected_pages:
            raise AppError(PROCESSING_FAILED, _FAILED_MESSAGE)
    finally:
        check_doc.close()

    result_size = staged.stat().st_size
    os.replace(staged, output_dir / RESULT_PDF)
    return PdfSplitResult(
        page_count=page_count,
        selected_pages=selected_pages,
        file_count=1,
        kind="pdf",
        result_size=result_size,
        result_name=RESULT_PDF,
    )


def _separate_mode(
    source: pymupdf.Document,
    work_dir: Path,
    output_dir: Path,
    ranges: list[tuple[int, int | None]],
    page_count: int,
) -> PdfSplitResult:
    staged_zip = work_dir / RESULT_ZIP
    digits = max(3, len(str(len(ranges))))
    total_selected = 0

    with zipfile.ZipFile(staged_zip, "w", compression=zipfile.ZIP_STORED) as archive:
        for index, (start, end) in enumerate(ranges, start=1):
            last = page_count if end is None else end
            part_pages = last - start + 1
            total_selected += part_pages

            part_doc = pymupdf.open()
            part_path = work_dir / f"part_{index}.pdf"
            try:
                part_doc.insert_pdf(
                    source,
                    from_page=start - 1,
                    to_page=last - 1,
                    links=True,
                    annots=True,
                )
                part_doc.save(str(part_path), garbage=3, deflate=True)
            finally:
                part_doc.close()

            check_doc = pymupdf.open(str(part_path))
            try:
                if check_doc.page_count != part_pages:
                    raise AppError(PROCESSING_FAILED, _FAILED_MESSAGE)
            finally:
                check_doc.close()

            part_name = f"part-{index:0{digits}d}.pdf"
            archive.write(part_path, arcname=part_name)
            part_path.unlink()

    with zipfile.ZipFile(staged_zip, "r") as check_archive:
        if len(check_archive.namelist()) != len(ranges):
            raise AppError(PROCESSING_FAILED, _FAILED_MESSAGE)

    result_size = staged_zip.stat().st_size
    os.replace(staged_zip, output_dir / RESULT_ZIP)
    return PdfSplitResult(
        page_count=page_count,
        selected_pages=total_selected,
        file_count=len(ranges),
        kind="zip",
        result_size=result_size,
        result_name=RESULT_ZIP,
    )
