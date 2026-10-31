"""PDF to PowerPoint engine.

One job turns one PDF into one .pptx with PyMuPDF and python-pptx: one slide
per page, in order. There are two modes.

* "pictures": every page is rendered to an image (150 DPI, lowered for very
  large pages) and placed as one picture covering its slide. It looks exactly
  like the PDF, but nothing on it can be edited.
* "editable": text and images are rebuilt as real PowerPoint objects. Each
  block of text becomes one text box, each line one paragraph and each span one
  run with its size, bold, italic and colour; each image becomes a picture.
  The real fonts are not preserved: every run uses Arial. Vector drawings
  (lines, shapes, backgrounds) are dropped, rotated text is not rotated,
  transparency masks on images are not applied, and because PowerPoint sets
  lines differently the layout can shift. A page with a non-zero rotation is
  rendered as a picture instead of transforming coordinates. Pictures go
  under the text, so the text stays readable and selectable.

Scanned pages stay pictures in both modes: there is no text recognition, so a
scan has no text to turn into text boxes.

A .pptx has one slide size. It is taken from the first page; every other page
is scaled to fit it and centred, so PDFs with mixed page sizes still work.

Only logs (server side) say why something failed; AppError messages stay
friendly and free of paths or exception text.
"""

import io
import logging
import math
import os
import re
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, get_args

import pymupdf
from PIL import Image
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.slide import Slide
from pptx.text.text import TextFrame
from pptx.util import Emu, Pt

from app.core.config import get_settings
from app.core.errors import INVALID_REQUEST, PROCESSING_FAILED, TOO_MANY_PAGES, AppError
from app.services.pdf_common import ConcurrencyGate, open_pdf_document

logger = logging.getLogger(__name__)

RESULT_PPTX = "result.pptx"

Mode = Literal["pictures", "editable"]

_WORK_PREFIX = ".work-"
_PPTX_MAIN_PART = "ppt/presentation.xml"
_SLIDE_PART = re.compile(r"ppt/slides/slide[0-9]+\.xml")
_BLANK_LAYOUT = 6
_FAILED_MESSAGE = (
    "Something went wrong while converting your PDF to PowerPoint. Please try again."
)

_EMU_PER_POINT = 12_700
_MIN_SLIDE_POINTS = 72.0
_MAX_SLIDE_POINTS = 4000.0  # PowerPoint's limit is 56 inches, 4032 points
# The range python-pptx accepts for a slide side (1 inch to 56 inches).
_MIN_SLIDE_EMU = 914_400
_MAX_SLIDE_EMU = 51_206_400

_PICTURE_DPI = 150
_JPEG_QUALITY = 85
_MAX_SIDE_PIXELS = 65_000  # a JPEG cannot be larger than 65535 pixels on a side

_FONT_NAME = "Arial"
_DEFAULT_FONT_POINTS = 12.0
_MIN_FONT_POINTS = 1.0
_MAX_FONT_POINTS = 4000.0
_ITALIC_FLAG = 2
_BOLD_FLAG = 16

# Characters an .pptx (XML 1.0) cannot hold: the C0 controls except tab, line
# feed and carriage return, lone surrogates, and the two non-characters.
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]")

_gate = ConcurrencyGate()
rebuild_concurrency_gate = _gate.rebuild


@dataclass(frozen=True)
class PdfToPptxResult:
    """What the caller needs to build a response and the job metadata."""

    page_count: int
    slide_count: int
    mode: Mode
    result_size: int
    result_name: str


@dataclass(frozen=True)
class _Placement:
    """Where a page sits on the slide: a uniform scale and an offset in points."""

    scale: float
    left: float
    top: float


def parse_mode(raw: object) -> Mode:
    """Return the mode if `raw` is exactly pictures or editable.

    Raises invalid_request for anything else, including None.
    """
    for mode in get_args(Mode):
        if raw == mode:
            return mode
    raise AppError(INVALID_REQUEST, "Please choose a mode: pictures or editable.")


def convert_pdf_to_pptx(
    input_path: Path, output_dir: Path, mode: Mode
) -> PdfToPptxResult:
    """Build result.pptx inside `output_dir` from the PDF at `input_path`.

    Blocking and CPU heavy: call it from a worker thread. The concurrency slot
    is taken here, inside that thread. Every failure leaves as an AppError.
    """
    chosen = parse_mode(mode)
    try:
        with _gate.hold():
            return _convert_locked(input_path, output_dir, chosen)
    except AppError:
        raise
    except Exception as exc:
        # PyMuPDF, python-pptx, Pillow and zipfile raise many unrelated types;
        # the client only needs to know that processing failed.
        logger.exception("PDF to PowerPoint failed unexpectedly")
        raise AppError(PROCESSING_FAILED, _FAILED_MESSAGE) from exc


def _convert_locked(
    input_path: Path, output_dir: Path, mode: Mode
) -> PdfToPptxResult:
    settings = get_settings()

    # Unlike the Word and Excel engines, the document stays open while the
    # presentation is built: the pages are rendered and read from it.
    document = open_pdf_document(input_path)
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
            staged = work_dir / RESULT_PPTX
            slide_count = _build_presentation(document, mode, staged)
            _check_pptx(staged, slide_count)
            result_size = staged.stat().st_size
            os.replace(staged, output_dir / RESULT_PPTX)
            return PdfToPptxResult(
                page_count=page_count,
                slide_count=slide_count,
                mode=mode,
                result_size=result_size,
                result_name=RESULT_PPTX,
            )
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)
    finally:
        document.close()


# -- Geometry ------------------------------------------------------------------


def _is_usable_size(width_pt: float, height_pt: float) -> bool:
    return (
        math.isfinite(width_pt)
        and math.isfinite(height_pt)
        and width_pt > 0
        and height_pt > 0
    )


def _slide_size(width_pt: float, height_pt: float) -> tuple[int, int]:
    """The slide size in EMU, from the first page's size in points.

    Scaled up uniformly if the shortest side is under 72 points, then scaled
    down uniformly if the longest side is over 4000 points; the upper limit
    wins when both cannot hold (a very long, thin page). The result is clamped
    to the range python-pptx accepts, so rounding can never make it refuse.
    """
    if not _is_usable_size(width_pt, height_pt):
        raise ValueError("page has no usable size")
    scale = 1.0
    shortest = min(width_pt, height_pt)
    if shortest < _MIN_SLIDE_POINTS:
        scale = _MIN_SLIDE_POINTS / shortest
    longest = max(width_pt, height_pt) * scale
    if longest > _MAX_SLIDE_POINTS:
        scale *= _MAX_SLIDE_POINTS / longest

    def to_emu(points: float) -> int:
        return max(_MIN_SLIDE_EMU, min(_MAX_SLIDE_EMU, round(points * _EMU_PER_POINT)))

    return to_emu(width_pt * scale), to_emu(height_pt * scale)


def _placement(
    page_width_pt: float, page_height_pt: float, slide_width: int, slide_height: int
) -> _Placement:
    """Scale a page to fit the slide, keep its aspect ratio and centre it."""
    if not _is_usable_size(page_width_pt, page_height_pt):
        raise ValueError("page has no usable size")
    slide_width_pt = slide_width / _EMU_PER_POINT
    slide_height_pt = slide_height / _EMU_PER_POINT
    scale = min(slide_width_pt / page_width_pt, slide_height_pt / page_height_pt)
    return _Placement(
        scale=scale,
        left=(slide_width_pt - page_width_pt * scale) / 2,
        top=(slide_height_pt - page_height_pt * scale) / 2,
    )


def _box(
    placement: _Placement, x0: float, y0: float, x1: float, y1: float
) -> tuple[Emu, Emu, Emu, Emu]:
    """A rectangle in page points as (left, top, width, height) in slide EMU."""
    scale = placement.scale
    left = round((placement.left + x0 * scale) * _EMU_PER_POINT)
    top = round((placement.top + y0 * scale) * _EMU_PER_POINT)
    width = max(1, round((x1 - x0) * scale * _EMU_PER_POINT))
    height = max(1, round((y1 - y0) * scale * _EMU_PER_POINT))
    return Emu(left), Emu(top), Emu(width), Emu(height)


# -- Building ------------------------------------------------------------------


def _build_presentation(
    document: pymupdf.Document, mode: Mode, destination: Path
) -> int:
    """Write one slide per page to `destination` and return the slide count."""
    max_pixels = get_settings().max_render_pixels
    first = document.load_page(0).rect
    slide_width, slide_height = _slide_size(first.width, first.height)

    presentation = Presentation()
    presentation.slide_width = Emu(slide_width)
    presentation.slide_height = Emu(slide_height)
    layout = presentation.slide_layouts[_BLANK_LAYOUT]

    for index in range(document.page_count):
        page = document.load_page(index)
        rect = page.rect
        placement = _placement(rect.width, rect.height, slide_width, slide_height)
        slide = presentation.slides.add_slide(layout)
        _fill_slide(document, page, index + 1, slide, mode, placement, max_pixels)

    presentation.save(str(destination))
    return len(presentation.slides)


def _fill_slide(
    document: pymupdf.Document,
    page: pymupdf.Page,
    page_number: int,
    slide: Slide,
    mode: Mode,
    placement: _Placement,
    max_pixels: int,
) -> None:
    if mode == "editable":
        if page.rotation == 0:
            _add_images(document, page, page_number, slide, placement)
            _add_text(page, slide, placement)
            return
        logger.info("Page %s is rotated; its slide is a picture", page_number)
    _add_page_picture(page, slide, placement, max_pixels)


# -- Pictures ------------------------------------------------------------------


def _fits(width_pt: float, height_pt: float, dpi: int, max_pixels: int) -> bool:
    """Whether a page rendered at `dpi` stays inside the pixel budget.

    The estimate adds a pixel per side because rounding can.
    """
    width_px = math.ceil(width_pt * dpi / 72) + 1
    height_px = math.ceil(height_pt * dpi / 72) + 1
    return (
        width_px * height_px <= max_pixels
        and max(width_px, height_px) <= _MAX_SIDE_PIXELS
    )


def _fit_dpi(width_pt: float, height_pt: float, max_pixels: int) -> int:
    """150 DPI, lowered for an oversized page instead of failing.

    Raises ValueError only for a page with no usable size or one so large that
    even 1 DPI would not fit the budget, where rendering would exhaust memory.
    """
    if not _is_usable_size(width_pt, height_pt):
        raise ValueError("page has no usable size")
    if _fits(width_pt, height_pt, _PICTURE_DPI, max_pixels):
        return _PICTURE_DPI

    area_square_inches = (width_pt / 72) * (height_pt / 72)
    limit = min(
        float(_PICTURE_DPI),
        math.sqrt(max_pixels / area_square_inches),
        _MAX_SIDE_PIXELS * 72 / max(width_pt, height_pt),
    )
    dpi = max(1, int(limit))
    while dpi > 1 and not _fits(width_pt, height_pt, dpi, max_pixels):
        dpi -= 1
    if not _fits(width_pt, height_pt, dpi, max_pixels):
        raise ValueError("page is too large to render")
    return dpi


def _encode_jpeg(pixmap: pymupdf.Pixmap) -> bytes:
    """JPEG bytes (quality 85) from a pixmap's samples, through Pillow.

    The pixmap rows can be padded, so the stride is passed along. A grayscale
    pixmap is converted to RGB. Every image is closed once the bytes exist.
    """
    if pixmap.n == 1:
        mode = "L"
    elif pixmap.n == 3:
        mode = "RGB"
    else:
        raise ValueError("unexpected pixmap layout")

    source = Image.frombuffer(
        mode,
        (pixmap.width, pixmap.height),
        pixmap.samples,
        "raw",
        mode,
        pixmap.stride,
        1,
    )
    try:
        image = source.convert("RGB") if mode == "L" else source
        try:
            with io.BytesIO() as buffer:
                image.save(buffer, format="JPEG", quality=_JPEG_QUALITY)
                return buffer.getvalue()
        finally:
            if image is not source:
                image.close()
    finally:
        source.close()


def _render_jpeg(page: pymupdf.Page, max_pixels: int) -> bytes:
    """Render one page on a white background and return it as JPEG bytes.

    The pixmap lives only inside this function, so it is released as soon as
    the bytes exist and no more than one page is ever held.
    """
    rect = page.rect
    dpi = _fit_dpi(rect.width, rect.height, max_pixels)
    pixmap = page.get_pixmap(dpi=dpi, alpha=False)
    try:
        return _encode_jpeg(pixmap)
    finally:
        del pixmap


def _add_page_picture(
    page: pymupdf.Page, slide: Slide, placement: _Placement, max_pixels: int
) -> None:
    """Cover the page's area of the slide with one picture of the page."""
    rect = page.rect
    data = _render_jpeg(page, max_pixels)
    left, top, width, height = _box(placement, 0, 0, rect.width, rect.height)
    with io.BytesIO(data) as stream:
        slide.shapes.add_picture(stream, left, top, width, height)


# -- Editable objects ----------------------------------------------------------


def _clean_text(text: str) -> str:
    """Text python-pptx accepts: no XML-incompatible characters, one line."""
    return _CONTROL_CHARS.sub("", text).replace("\r", " ").replace("\n", " ")


def _font_size(raw: object, scale: float) -> float:
    """A run's size in points on the slide: never below 1, never above 4000."""
    try:
        size = float(raw) * scale  # type: ignore[arg-type]
    except (TypeError, ValueError):
        size = _DEFAULT_FONT_POINTS * scale
    if not math.isfinite(size):
        size = _DEFAULT_FONT_POINTS * scale
    return min(max(size, _MIN_FONT_POINTS), _MAX_FONT_POINTS)


def _block_lines(block: dict[str, Any]) -> list[list[tuple[str, dict[str, Any]]]]:
    """The non-empty lines of a text block, each as (text, span) pairs."""
    lines: list[list[tuple[str, dict[str, Any]]]] = []
    for line in block["lines"]:
        pairs = [(_clean_text(span["text"]), span) for span in line["spans"]]
        if not "".join(text for text, _span in pairs).strip():
            continue
        lines.append([(text, span) for text, span in pairs if text])
    return lines


def _write_line(
    frame: TextFrame,
    line: list[tuple[str, dict[str, Any]]],
    first: bool,
    scale: float,
) -> None:
    """One line becomes one paragraph, and each span one run."""
    paragraph = frame.paragraphs[0] if first else frame.add_paragraph()
    for text, span in line:
        run = paragraph.add_run()
        run.text = text
        font = run.font
        font.name = _FONT_NAME
        font.size = Pt(_font_size(span["size"], scale))
        flags = int(span["flags"])
        if flags & _BOLD_FLAG:
            font.bold = True
        if flags & _ITALIC_FLAG:
            font.italic = True
        color = span["color"]
        if isinstance(color, int):
            font.color.rgb = RGBColor(
                (color >> 16) & 0xFF, (color >> 8) & 0xFF, color & 0xFF
            )


def _add_text(page: pymupdf.Page, slide: Slide, placement: _Placement) -> None:
    """One text box per text block, at the block's place on the page.

    Wrapping is off and the margins are zero so the text starts exactly where
    it did in the PDF. Image blocks are not requested from PyMuPDF at all.
    """
    flags = (
        pymupdf.TEXT_PRESERVE_LIGATURES
        | pymupdf.TEXT_PRESERVE_WHITESPACE
        | pymupdf.TEXT_MEDIABOX_CLIP
    )
    content = page.get_text("dict", flags=flags)
    for block in content["blocks"]:
        if block["type"] != 0:
            continue
        lines = _block_lines(block)
        if not lines:
            continue
        x0, y0, x1, y1 = block["bbox"]
        left, top, width, height = _box(placement, x0, y0, x1, y1)
        frame = slide.shapes.add_textbox(left, top, width, height).text_frame
        frame.word_wrap = False
        frame.margin_left = Emu(0)
        frame.margin_right = Emu(0)
        frame.margin_top = Emu(0)
        frame.margin_bottom = Emu(0)
        for number, line in enumerate(lines):
            _write_line(frame, line, number == 0, placement.scale)


def _add_images(
    document: pymupdf.Document,
    page: pymupdf.Page,
    page_number: int,
    slide: Slide,
    placement: _Placement,
) -> None:
    """One picture per distinct image on the page, at its place on the page.

    Each image is on its own: one that python-pptx cannot read (JPX and other
    formats) is skipped and logged, and never fails the job.
    """
    seen: set[int] = set()
    for entry in page.get_image_info(xrefs=True):
        xref = entry.get("xref", 0)
        if not xref or xref in seen:
            continue
        seen.add(xref)
        try:
            extracted = document.extract_image(xref)
            data = extracted["image"] if extracted else None
            if not data:
                raise ValueError("no image data")
            x0, y0, x1, y1 = entry["bbox"]
            left, top, width, height = _box(placement, x0, y0, x1, y1)
            with io.BytesIO(data) as stream:
                slide.shapes.add_picture(stream, left, top, width, height)
        except Exception as exc:  # noqa: BLE001 - one unreadable image must never fail the job
            logger.info("Image %s on page %s skipped: %s", xref, page_number, exc)


# -- Checking ------------------------------------------------------------------


def _check_pptx(path: Path, expected_slides: int) -> None:
    """Raise ValueError unless `path` is a PowerPoint package with that many slides."""
    if not path.is_file() or path.stat().st_size == 0:
        raise ValueError("presentation was not written")
    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
    except zipfile.BadZipFile as exc:
        raise ValueError("output is not a zip file") from exc
    if _PPTX_MAIN_PART not in names:
        raise ValueError("output is not a PowerPoint presentation")
    slides = [name for name in names if _SLIDE_PART.fullmatch(name)]
    if len(slides) != expected_slides:
        raise ValueError("output has the wrong number of slides")