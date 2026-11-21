"""Render supported Office files into searchable PDFs with bundled libraries."""

import logging
import os
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import pymupdf
from docx import Document
from openpyxl import load_workbook
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE

from app.core.config import get_settings
from app.core.errors import PROCESSING_FAILED, TOO_MANY_PAGES, AppError
from app.services.pdf_common import ConcurrencyGate

logger = logging.getLogger(__name__)
OfficeKind = Literal["word", "powerpoint", "excel"]
RESULT_NAME = "result.pdf"
_gate = ConcurrencyGate()
rebuild_concurrency_gate = _gate.rebuild


@dataclass(frozen=True)
class OfficeResult:
    page_count: int
    result_size: int
    result_name: str = RESULT_NAME


def _plain(text: object) -> str:
    """Builtin PDF fonts cover Latin text; replace unsupported glyphs safely."""
    return str(text).encode("latin-1", "replace").decode("latin-1")


class _Flow:
    def __init__(self, pdf: pymupdf.Document) -> None:
        self.pdf = pdf
        self.page: pymupdf.Page | None = None
        self.y = 50.0

    def line(self, value: object, *, heading: bool = False) -> None:
        text = _plain(value).strip()
        if not text:
            self.y += 8
            return
        size = 14 if heading else 10
        width = 80 if heading else 100
        chunks = [text[i : i + width] for i in range(0, len(text), width)]
        for chunk in chunks:
            if self.page is None or self.y > 790:
                self.page = self.pdf.new_page(width=595, height=842)
                self.y = 50
            self.page.insert_text((45, self.y), chunk, fontsize=size)
            self.y += size * 1.5


def _word(path: Path, pdf: pymupdf.Document) -> None:
    document = Document(path)
    flow = _Flow(pdf)
    for block in document.iter_inner_content():
        if hasattr(block, "rows"):
            for row in block.rows:
                flow.line(" | ".join(cell.text for cell in row.cells))
        else:
            flow.line(block.text, heading=block.style.name.startswith("Heading"))
    if pdf.page_count == 0:
        pdf.new_page(width=595, height=842)


def _powerpoint(path: Path, pdf: pymupdf.Document) -> None:
    presentation = Presentation(path)
    scale = min(842 / presentation.slide_height, 595 / presentation.slide_width)
    width = presentation.slide_width * scale
    height = presentation.slide_height * scale
    for slide in presentation.slides:
        page = pdf.new_page(width=width, height=height)
        for shape in slide.shapes:
            box = pymupdf.Rect(
                shape.left * scale,
                shape.top * scale,
                (shape.left + shape.width) * scale,
                (shape.top + shape.height) * scale,
            )
            if box.is_empty:
                continue
            if shape.shape_type == MSO_SHAPE_TYPE.PICTURE:
                page.insert_image(box, stream=shape.image.blob, keep_proportion=True)
            elif shape.has_text_frame and shape.text.strip():
                page.insert_textbox(box, _plain(shape.text), fontsize=12)
    if pdf.page_count == 0:
        pdf.new_page(width=595, height=842)


def _excel(path: Path, pdf: pymupdf.Document) -> None:
    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        flow = _Flow(pdf)
        for sheet in workbook:
            flow.line(sheet.title, heading=True)
            for row in sheet.iter_rows(values_only=True):
                values = [str(cell) if cell is not None else "" for cell in row]
                if any(values):
                    flow.line(" | ".join(values).rstrip(" |"))
        if pdf.page_count == 0:
            pdf.new_page(width=595, height=842)
    finally:
        workbook.close()


def convert_office_to_pdf(
    input_path: Path, output_dir: Path, kind: OfficeKind
) -> OfficeResult:
    """Convert a valid Office package, keeping text searchable where possible."""
    try:
        with _gate.hold():
            pdf = pymupdf.open()
            try:
                {"word": _word, "powerpoint": _powerpoint, "excel": _excel}[kind](
                    input_path, pdf
                )
                if pdf.page_count > get_settings().max_pdf_pages:
                    raise AppError(TOO_MANY_PAGES)
                with tempfile.NamedTemporaryFile(
                    suffix=".pdf", dir=output_dir, delete=False
                ) as temp:
                    staged = Path(temp.name)
                try:
                    pdf.save(str(staged), garbage=3, deflate=True)
                    os.replace(staged, output_dir / RESULT_NAME)
                finally:
                    staged.unlink(missing_ok=True)
                return OfficeResult(pdf.page_count, (output_dir / RESULT_NAME).stat().st_size)
            finally:
                pdf.close()
    except AppError:
        raise
    except (ValueError, KeyError, zipfile.BadZipFile) as exc:
        raise AppError("not_office") from exc
    except Exception as exc:
        logger.exception("Office to PDF conversion failed")
        raise AppError(PROCESSING_FAILED, "We couldn't convert this Office file. Please try another copy.") from exc
