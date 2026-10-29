"""JPG/PNG to PDF engine.

One job turns an ordered list of pictures into one PDF, one page per picture:

* a JPEG or PNG that a PDF can hold as it is (RGB or grayscale, upright, no
  transparency) is embedded untouched, so JPEGs are not re-compressed;
* anything else (CMYK, palette, 16-bit, transparency, EXIF rotation) is first
  normalised with Pillow into a private temporary file: transparency is
  composited onto white, rotation is applied, JPEGs are re-encoded once at high
  quality and PNGs stay lossless.

"fit" makes each page the size of its picture (using the picture's DPI tag,
96 DPI when it has none, and never beyond what PDF viewers accept); "a4" puts
each picture centred on an A4 page, portrait or landscape to match, with a
10 mm margin. Client file names are never used. Only logs (server side) say why
something failed; AppError messages stay friendly and free of paths.
"""

import logging
import os
import shutil
import tempfile
import threading
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import get_args

import pymupdf
from PIL import Image, ImageOps

from app.core.config import get_settings
from app.core.errors import (
    INVALID_PAGE_SIZE,
    INVALID_REQUEST,
    NOT_IMAGE,
    PROCESSING_FAILED,
    TOO_LARGE,
    AppError,
)
from app.schemas.jobs import PageSize

logger = logging.getLogger(__name__)

RESULT_PDF = "result.pdf"

_WORK_PREFIX = ".work-"
_JPEG_MAGIC = b"\xff\xd8\xff"
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
# Pillow reports JPEGs that carry a multi-picture block (many phone photos) as
# "MPO", which is still an ordinary JPEG for our purposes.
_FORMATS = {"jpeg": ("JPEG", "MPO"), "png": ("PNG",)}
_MAX_PIXELS = 80_000_000  # per picture; below Pillow's own decompression-bomb limit
_A4_PORTRAIT = (595.0, 842.0)  # points
_MARGIN_POINTS = 28.0  # about 10 mm
_DEFAULT_DPI = 96.0
_MIN_DPI = 30.0
_MAX_DPI = 1200.0
_MAX_PAGE_POINTS = 14_400.0  # 200 inches, the most PDF viewers accept
_JPEG_QUALITY = 92
_EXIF_ORIENTATION = 0x0112
_DIRECT_MODES = ("RGB", "L")
_FAILED_MESSAGE = "Something went wrong while building your PDF. Please try again."


@dataclass(frozen=True)
class JpgToPdfResult:
    """What the caller needs to build a response and the job metadata."""

    page_count: int
    result_size: int
    result_name: str


@dataclass(frozen=True)
class _Prepared:
    """A picture ready to embed: the file to read and its upright pixel size."""

    path: Path
    width_px: int
    height_px: int
    dpi: float


# -- Concurrency ---------------------------------------------------------------

# Each engine owns its gate (MAX_CONCURRENT_JOBS per tool), like pdf_to_jpg.
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


def parse_page_size(raw: object) -> PageSize:
    """Return the page size if `raw` is exactly fit or a4.

    Raises invalid_page_size for anything else, including None.
    """
    for size in get_args(PageSize):
        if raw == size:
            return size
    raise AppError(INVALID_PAGE_SIZE)


def convert_images_to_pdf(
    input_paths: Sequence[Path], output_dir: Path, page_size: PageSize
) -> JpgToPdfResult:
    """Build result.pdf inside `output_dir` from the pictures, in the given order.

    Blocking and CPU heavy: call it from a worker thread. The concurrency gate
    is acquired here, inside that thread, so waiting jobs never block the event
    loop. Every failure leaves as an AppError.
    """
    parse_page_size(page_size)
    if not input_paths:
        raise AppError(INVALID_REQUEST)
    gate = _get_gate()
    gate.acquire()
    try:
        return _convert_locked(input_paths, output_dir, page_size)
    except AppError:
        raise
    except Exception as exc:
        # PyMuPDF and Pillow raise many unrelated types; the client only needs
        # to know that processing failed.
        logger.exception("JPG to PDF failed unexpectedly")
        raise AppError(PROCESSING_FAILED, _FAILED_MESSAGE) from exc
    finally:
        gate.release()


# -- Orchestration -------------------------------------------------------------


def _convert_locked(
    input_paths: Sequence[Path], output_dir: Path, page_size: PageSize
) -> JpgToPdfResult:
    # Inside the job's output folder so the sweeper also covers leftovers.
    work_dir = Path(tempfile.mkdtemp(prefix=_WORK_PREFIX, dir=output_dir))
    try:
        prepared = [
            _prepare_one(path, number, work_dir)
            for number, path in enumerate(input_paths, start=1)
        ]
        staged = work_dir / RESULT_PDF
        _build_pdf(prepared, page_size, staged)
        if _page_count(staged) != len(prepared):
            logger.error("The built PDF has the wrong number of pages")
            raise AppError(PROCESSING_FAILED, _FAILED_MESSAGE)
        result_size = staged.stat().st_size
        os.replace(staged, output_dir / RESULT_PDF)
        return JpgToPdfResult(
            page_count=len(prepared),
            result_size=result_size,
            result_name=RESULT_PDF,
        )
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


# -- Preparing pictures --------------------------------------------------------


def _not_image(number: int) -> AppError:
    return AppError(
        NOT_IMAGE,
        f"Image {number} doesn't look like a JPG or PNG picture. "
        "Please choose JPG or PNG images and try again.",
    )


def _too_many_pixels(number: int) -> AppError:
    return AppError(
        TOO_LARGE,
        f"Image {number} has too many pixels to process. "
        "Please shrink it and try again.",
    )


def _sniff(path: Path) -> str | None:
    """Tell JPEG from PNG by the first bytes, never by the extension."""
    with path.open("rb") as handle:
        head = handle.read(len(_PNG_MAGIC))
    if head.startswith(_JPEG_MAGIC):
        return "jpeg"
    if head.startswith(_PNG_MAGIC):
        return "png"
    return None


def _read_dpi(image: Image.Image) -> float:
    """The picture's DPI tag, or a default when it is missing or silly."""
    raw = image.info.get("dpi")
    try:
        value = float(raw[0])
    except (TypeError, ValueError, IndexError, KeyError):
        return _DEFAULT_DPI
    if not _MIN_DPI <= value <= _MAX_DPI:
        return _DEFAULT_DPI
    return value


def _exif_orientation(image: Image.Image) -> int | None:
    try:
        value = image.getexif().get(_EXIF_ORIENTATION)
    except Exception:  # noqa: BLE001 - damaged EXIF must not reject an otherwise good image
        return None
    return value if isinstance(value, int) else None


def _has_transparency(image: Image.Image) -> bool:
    return image.mode in ("RGBA", "LA", "PA") or "transparency" in image.info


def _flatten_to_rgb(image: Image.Image) -> Image.Image:
    """An RGB copy of any picture, with transparency composited onto white."""
    if _has_transparency(image):
        rgba = image.convert("RGBA")
        try:
            background = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
            try:
                background.alpha_composite(rgba)
                return background.convert("RGB")
            finally:
                background.close()
        finally:
            rgba.close()
    return image.convert("RGB")


def _normalise(
    image: Image.Image, kind: str, number: int, work_dir: Path, dpi: float
) -> _Prepared:
    """Write an upright, opaque RGB or gray copy that a PDF can embed."""
    upright = ImageOps.exif_transpose(image)
    if upright is None:
        upright = image.copy()
    converted: Image.Image | None = None
    try:
        if upright.mode == "L" and not _has_transparency(upright):
            target = upright
        else:
            converted = _flatten_to_rgb(upright)
            target = converted
        if kind == "png":
            output = work_dir / f"{number:03d}.png"
            target.save(output, format="PNG")
        else:
            output = work_dir / f"{number:03d}.jpg"
            target.save(output, format="JPEG", quality=_JPEG_QUALITY)
        return _Prepared(output, target.width, target.height, dpi)
    finally:
        if converted is not None:
            converted.close()
        upright.close()


def _prepare_opened(
    image: Image.Image, kind: str, source: Path, number: int, work_dir: Path
) -> _Prepared:
    if image.format not in _FORMATS[kind]:
        raise _not_image(number)
    width, height = image.size
    if width < 1 or height < 1:
        raise _not_image(number)
    if width * height > _MAX_PIXELS:
        raise _too_many_pixels(number)

    dpi = _read_dpi(image)
    orientation = _exif_orientation(image)
    embeddable_as_is = (
        image.mode in _DIRECT_MODES
        and orientation in (None, 1)
        and "transparency" not in image.info
    )
    if embeddable_as_is:
        return _Prepared(source, width, height, dpi)
    return _normalise(image, kind, number, work_dir, dpi)


def _prepare_one(source: Path, number: int, work_dir: Path) -> _Prepared:
    """Validate one picture and return what to embed for it.

    The AppError is raised only after the except blocks have ended, so no
    traceback keeps a half-read image alive (on Windows that can leave a file
    open and block cleanup).
    """
    kind = _sniff(source)
    if kind is None:
        raise _not_image(number)

    problem: AppError | None = None
    prepared: _Prepared | None = None
    try:
        with Image.open(source) as image:
            prepared = _prepare_opened(image, kind, source, number, work_dir)
    except AppError as exc:
        problem = exc
    except Image.DecompressionBombError:
        problem = _too_many_pixels(number)
    except Exception as exc:  # noqa: BLE001 - Pillow raises many unrelated types for damaged or hostile files
        logger.info("Image %s could not be read: %s", number, type(exc).__name__)
        problem = _not_image(number)
    if problem is not None:
        raise problem
    if prepared is None:
        raise _not_image(number)
    return prepared


# -- Building the PDF ----------------------------------------------------------


def _layout(item: _Prepared, page_size: PageSize) -> tuple[float, float, pymupdf.Rect]:
    """The page size in points and where the picture goes on it."""
    if page_size == "a4":
        portrait_width, portrait_height = _A4_PORTRAIT
        if item.width_px > item.height_px:
            page_width, page_height = portrait_height, portrait_width
        else:
            page_width, page_height = portrait_width, portrait_height
        scale = min(
            (page_width - 2 * _MARGIN_POINTS) / item.width_px,
            (page_height - 2 * _MARGIN_POINTS) / item.height_px,
        )
        width = item.width_px * scale
        height = item.height_px * scale
        left = (page_width - width) / 2
        top = (page_height - height) / 2
        rect = pymupdf.Rect(left, top, left + width, top + height)
        return page_width, page_height, rect

    width = item.width_px * 72.0 / item.dpi
    height = item.height_px * 72.0 / item.dpi
    longest = max(width, height)
    if longest > _MAX_PAGE_POINTS:
        shrink = _MAX_PAGE_POINTS / longest
        width *= shrink
        height *= shrink
    width = max(width, 1.0)
    height = max(height, 1.0)
    return width, height, pymupdf.Rect(0, 0, width, height)


def _build_pdf(
    items: Sequence[_Prepared], page_size: PageSize, destination: Path
) -> None:
    """One page per picture, in order. Each picture is read just before use."""
    document = pymupdf.open()
    try:
        for item in items:
            width, height, rect = _layout(item, page_size)
            page = document.new_page(width=width, height=height)
            page.insert_image(rect, stream=item.path.read_bytes())
        document.save(str(destination), garbage=3, deflate=True)
    finally:
        document.close()


def _page_count(path: Path) -> int:
    document = pymupdf.open(str(path))
    try:
        return document.page_count
    finally:
        document.close()