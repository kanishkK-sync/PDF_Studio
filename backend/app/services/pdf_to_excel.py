"""PDF to Excel engine.

One job turns one PDF into one .xlsx with pdfplumber and openpyxl:

* when the PDF contains tables, each table becomes its own sheet ("P1 T1" is
  the first table on page 1);
* when it contains none, the text of every page goes to a single "Text" sheet
  instead, one line per row with its page number, so a text-only PDF still
  gives something useful.

pdfplumber finds tables from ruling lines and text alignment, so it works well
on real tables and poorly on scans: there is no text recognition, so a PDF
with neither tables nor text fails with a clear message instead of producing
an empty workbook.

Cell text is cleaned of control characters, and text that starts with "="
is stored as plain text, so a hostile PDF cannot plant a formula. Only logs
(server side) say why something failed; AppError messages stay friendly and
free of paths or exception text.
"""

import logging
import os
import re
import shutil
import tempfile
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import pdfplumber
from openpyxl import Workbook
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from app.core.config import get_settings
from app.core.errors import NO_CONTENT, PROCESSING_FAILED, TOO_MANY_PAGES, AppError
from app.services.pdf_common import ConcurrencyGate, open_pdf_document

logger = logging.getLogger(__name__)

RESULT_XLSX = "result.xlsx"

Mode = Literal["tables", "text"]

_WORK_PREFIX = ".work-"
_XLSX_MAIN_PART = "xl/workbook.xml"
_TEXT_SHEET = "Text"
_SHEET_TITLE_MAX = 31  # Excel's own limit
_MIN_TABLE_ROWS = 2
_MIN_TABLE_COLUMNS = 2
_COLUMN_PADDING = 2
_MAX_COLUMN_WIDTH = 60
_FAILED_MESSAGE = (
    "Something went wrong while converting your PDF to Excel. Please try again."
)

# Control characters Excel cannot store (tab, line feed and carriage return are
# fine and are kept).
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_ILLEGAL_TITLE_CHARS = re.compile(r"[\[\]:*?/\\]")

_gate = ConcurrencyGate()
rebuild_concurrency_gate = _gate.rebuild


@dataclass(frozen=True)
class PdfToExcelResult:
    """What the caller needs to build a response and the job metadata."""

    page_count: int
    table_count: int
    sheet_count: int
    mode: Mode
    result_size: int
    result_name: str


@dataclass(frozen=True)
class _Table:
    """One table: its page (1-based), its position on that page and its rows."""

    page: int
    index: int
    rows: list[list[str]]


@dataclass(frozen=True)
class _Content:
    """What was found in the PDF: tables, or (only if none) text lines."""

    tables: list[_Table]
    lines: list[tuple[int, str]]


def convert_pdf_to_excel(input_path: Path, output_dir: Path) -> PdfToExcelResult:
    """Build result.xlsx inside `output_dir` from the PDF at `input_path`.

    Blocking and CPU heavy: call it from a worker thread. The concurrency slot
    is taken here, inside that thread. Every failure leaves as an AppError.
    """
    try:
        with _gate.hold():
            return _convert_locked(input_path, output_dir)
    except AppError:
        raise
    except Exception as exc:
        # pdfplumber, PyMuPDF, openpyxl and zipfile raise many unrelated types;
        # the client only needs to know that processing failed.
        logger.exception("PDF to Excel failed unexpectedly")
        raise AppError(PROCESSING_FAILED, _FAILED_MESSAGE) from exc


def _convert_locked(input_path: Path, output_dir: Path) -> PdfToExcelResult:
    settings = get_settings()

    document = open_pdf_document(input_path)
    try:
        page_count = document.page_count
    finally:
        # Closed before pdfplumber opens the same file again.
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
        staged = work_dir / RESULT_XLSX
        content = _read_pdf(input_path)
        sheet_count = _write_workbook(content, staged)
        _check_xlsx(staged)
        result_size = staged.stat().st_size
        os.replace(staged, output_dir / RESULT_XLSX)
        mode: Mode = "tables" if content.tables else "text"
        return PdfToExcelResult(
            page_count=page_count,
            table_count=len(content.tables),
            sheet_count=sheet_count,
            mode=mode,
            result_size=result_size,
            result_name=RESULT_XLSX,
        )
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


# -- Reading the PDF -----------------------------------------------------------


def _clean_cell(value: object) -> str:
    """Text safe for a worksheet: no control characters, trimmed, None as empty."""
    if value is None:
        return ""
    return _CONTROL_CHARS.sub("", str(value)).strip()


def _is_usable(rows: list[list[str]]) -> bool:
    """A table worth a sheet: several rows, a row with several cells, some text.

    This drops the single boxes and lines that pdfplumber sometimes reports as
    one-cell "tables".
    """
    if len(rows) < _MIN_TABLE_ROWS:
        return False
    if not any(len(row) >= _MIN_TABLE_COLUMNS for row in rows):
        return False
    return any(cell for row in rows for cell in row)


def _read_pdf(path: Path) -> _Content:
    """Find the tables; if there are none, collect the text lines instead.

    A page that pdfplumber cannot read fails the whole job (through the caller's
    isolation boundary): a silently missing page would be worse than an error.
    """
    tables: list[_Table] = []
    with pdfplumber.open(str(path)) as pdf:
        for number, page in enumerate(pdf.pages, start=1):
            index = 0
            for raw in page.extract_tables():
                rows = [[_clean_cell(cell) for cell in row] for row in raw]
                if not _is_usable(rows):
                    continue
                index += 1
                tables.append(_Table(page=number, index=index, rows=rows))
        if tables:
            return _Content(tables=tables, lines=[])

        lines: list[tuple[int, str]] = []
        for number, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            for raw_line in text.splitlines():
                line = _clean_cell(raw_line)
                if line:
                    lines.append((number, line))
    return _Content(tables=[], lines=lines)


# -- Writing the workbook ------------------------------------------------------


def _sheet_title(table: _Table) -> str:
    """"P1 T2": never longer than Excel allows, never with a forbidden character."""
    title = _ILLEGAL_TITLE_CHARS.sub("", f"P{table.page} T{table.index}")
    return title[:_SHEET_TITLE_MAX]


def _fill_sheet(sheet: Worksheet, rows: Sequence[Sequence[str | int]]) -> None:
    """Write the rows and give each column a width that fits its longest line.

    Empty cells are left blank. openpyxl treats a string that starts with "="
    as a formula, so such a cell is switched back to plain text right after it
    is assigned: the PDF's text is shown, never evaluated.
    """
    widths: dict[int, int] = {}
    for row_number, row in enumerate(rows, start=1):
        for column, value in enumerate(row, start=1):
            if value == "":
                continue
            cell = sheet.cell(row=row_number, column=column, value=value)
            if cell.data_type == "f":
                cell.data_type = "s"
            longest = max(len(part) for part in str(value).split("\n"))
            widths[column] = max(widths.get(column, 0), longest)
    for column, width in widths.items():
        letter = get_column_letter(column)
        sheet.column_dimensions[letter].width = min(
            width + _COLUMN_PADDING, _MAX_COLUMN_WIDTH
        )


def _write_workbook(content: _Content, destination: Path) -> int:
    """Save the workbook to `destination` and return how many sheets it has.

    Raises no_content when the PDF held neither tables nor text, because an
    empty workbook would only look like a bug to the user.
    """
    if not content.tables and not content.lines:
        raise AppError(NO_CONTENT)

    workbook = Workbook()
    try:
        # openpyxl starts with one empty sheet; it is removed once ours exist.
        starter = workbook.active
        if content.tables:
            for table in content.tables:
                sheet = workbook.create_sheet(title=_sheet_title(table))
                _fill_sheet(sheet, table.rows)
        else:
            sheet = workbook.create_sheet(title=_TEXT_SHEET)
            rows: list[list[str | int]] = [["Page", "Text"]]
            rows.extend([page, line] for page, line in content.lines)
            _fill_sheet(sheet, rows)
        if starter is not None:
            workbook.remove(starter)
        sheet_count = len(workbook.sheetnames)
        workbook.save(str(destination))
    finally:
        workbook.close()
    return sheet_count


def _check_xlsx(path: Path) -> None:
    """Raise ValueError unless `path` is a non-empty Excel workbook package."""
    if not path.is_file() or path.stat().st_size == 0:
        raise ValueError("workbook was not written")
    with zipfile.ZipFile(path) as archive:
        if _XLSX_MAIN_PART not in archive.namelist():
            raise ValueError("output is not an Excel workbook")