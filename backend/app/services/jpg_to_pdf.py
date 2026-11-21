"""JPG and PNG to PDF engine.

One job turns a list of images into one PDF, one page per image, in the order
given. Each image goes through a single pass, so only one image is ever
decoded at a time:

1. Inspect it with Pillow: it must open and be a JPEG or a PNG, stay under a
   pixel cap (a decompression-bomb guard), and, when it is to be embedded as
   is, decode completely (a truncated file fails here, not in a PDF viewer).
2. Embed it. A plain 8-bit RGB or grayscale JPEG with no EXIF rotation goes in
   byte for byte, so nothing is lost. Everything else is first re-encoded by
   Pillow into the job's work folder: JPEGs that are rotated, CMYK or
   otherwise unusual as JPEG at quality 92; PNGs as 8-bit PNG, with any
   transparency flattened onto white and palette or 16-bit data converted.
   If PyMuPDF refuses a direct embed, that image falls back to the re-encode.
3. Lay the page out: "fit" gives the image's own size; "a4" gives an A4 page
   (portrait or landscape to suit the image) with the image centred, its
   aspect kept and a 10 mm margin.

Client file names never reach this module: callers pass generated paths. Only
logs (server side) say why something failed; AppError messages stay friendly
and free of paths or exception text.
"""

import logging
import os
import shutil
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import get_args

import pymupdf
from PIL import Image, ImageOps

from app.core.errors import (
    INVALID_PAGE_SIZE,
    INVALID_REQUEST,
    NOT_IMAGE,
    PROCESSING_FAILED,
    TOO_LARGE,
    AppError,
)
from app.schemas.jobs import PageSize
from app.services.pdf_common import GLOBAL_GATE

logger = logging.getLogger(__name__)

RESULT_PDF = "result.pdf"

_WORK_PREFIX = ".work-"
_JPEG_QUALITY = 92
# Above this many pixels an image is refused. It sits below Pillow's own
# warning threshold (about 89 million), so allowed images never trigger it.
_MAX_IMAGE_PIXELS = 80_000_000
_JPEG_FORMATS = ("JPEG", "MPO")
_SIDEWAYS = (5, 6, 7, 8)  # EXIF orientations that swap width and height
_ORIENTATION_TAG = 0x0112
_UNREADABLE = "unreadable"
_TOO_MANY_PIXELS = "too_many_pixels"

_POINTS_PER_MM = 72 / 25.4
_A4_SHORT_PT = 210 * _POINTS_PER_MM
_A4_LONG_PT = 297 * _POINTS_PER_MM
_MARGIN_PT = 10 * _POINTS_PER_MM
_DEFAULT_DPI = 72.0  # without a usable DPI tag, one pixel is one point
_MIN_DPI = 30.0
_MAX_DPI = 2400.0
_MAX_PAGE_PT = 14_400.0  # the PDF page size limit most viewers honour
_MIN_PAGE_PT = 3.0

_FAILED_MESSAGE = "Something went wrong while creating your PDF. Please try again."


@dataclass(frozen=True)
class JpgToPdfResult:
    """What the caller needs to build a response and the job metadata."""

    page_count: int
    total_input_size: int
    result_size: int
    page_size: PageSize
    result_name: str


@dataclass(frozen=True)
class _Info:
    """What the engine learned about one image, with sizes after any rotation."""

    jpeg: bool  # JPEG family (JPEG, MPO) rather than PNG
    width: int
    height: int
    dpi: tuple[float, float] | None
    direct: bool  # can be embedded byte for byte


# -- Concurrency ---------------------------------------------------------------

rebuild_concurrency_gate = GLOBAL_GATE.rebuild


# -- Public API ----------------------------------------------------------------


def parse_page_size(raw: object) -> PageSize:
    """Return the page size if `raw` is exactly fit or a4.

    Raises invalid_page_size for anything else, including None.
    """
    for page_size in get_args(PageSize):
        if raw == page_size:
            return page_size
    raise AppError(INVALID_PAGE_SIZE)


def not_image_message(position: int) -> str:
    """The not_image message for the image at this 1-based position in the batch."""
    return (
        f"Image {position} doesn't look like a valid JPG or PNG image. "
        "Please choose JPG or PNG images and try again."
    )


def convert_images_to_pdf(
    image_paths: Sequence[Path], output_dir: Path, page_size: PageSize
) -> JpgToPdfResult:
    """Build result.pdf inside `output_dir` from the images, one page each.

    Blocking and CPU heavy: call it from a worker thread. The concurrency gate
    is acquired here, inside that thread, so waiting jobs never block the event
    loop. Every failure leaves as an AppError.
    """
    parse_page_size(page_size)
    try:
        with GLOBAL_GATE.hold():
            return _convert_locked(image_paths, output_dir, page_size)
    except AppError:
        raise
    except Exception as exc:
        # PyMuPDF and Pillow raise many unrelated types; the client only needs
        # to know that processing failed.
        logger.exception("JPG to PDF failed unexpectedly")
        raise AppError(PROCESSING_FAILED, _FAILED_MESSAGE) from exc


# -- Orchestration -------------------------------------------------------------


def _convert_locked(
    image_paths: Sequence[Path], output_dir: Path, page_size: PageSize
) -> JpgToPdfResult:
    if not image_paths:
        raise AppError(INVALID_REQUEST)
    total_input_size = sum(path.stat().st_size for path in image_paths)

    # Inside the job's output folder so the sweeper also covers leftovers.
    work_dir = Path(tempfile.mkdtemp(prefix=_WORK_PREFIX, dir=output_dir))
    try:
        staged = work_dir / RESULT_PDF
        _build_pdf(image_paths, staged, work_dir, page_size)
        result_size = staged.stat().st_size
        os.replace(staged, output_dir / RESULT_PDF)
        return JpgToPdfResult(
            page_count=len(image_paths),
            total_input_size=total_input_size,
            result_size=result_size,
            page_size=page_size,
            result_name=RESULT_PDF,
        )
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def _build_pdf(
    image_paths: Sequence[Path],
    destination: Path,
    work_dir: Path,
    page_size: PageSize,
) -> None:
    document = pymupdf.open()
    try:
        for position, path in enumerate(image_paths, start=1):
            info = _inspect(path, position)
            _add_page(document, path, info, position, work_dir, page_size)
        document.save(str(destination), garbage=4, deflate=True)
    finally:
        document.close()
    _verify_output(destination, len(image_paths))


def _verify_output(path: Path, expected_pages: int) -> None:
    """Never hand back a PDF that lost a page."""
    document = pymupdf.open(str(path))
    try:
        found = document.page_count
    finally:
        document.close()
    if found != expected_pages:
        raise ValueError("the PDF has the wrong number of pages")


# -- Pages ---------------------------------------------------------------------


def _layout(info: _Info, page_size: PageSize) -> tuple[float, float, pymupdf.Rect]:
    """The page size in points and the rectangle the image fills on it."""
    if page_size == "a4":
        short, long = _A4_SHORT_PT, _A4_LONG_PT
        landscape = info.width > info.height
        page_width, page_height = (long, short) if landscape else (short, long)
        scale = min(
            (page_width - 2 * _MARGIN_PT) / info.width,
            (page_height - 2 * _MARGIN_PT) / info.height,
        )
        width = info.width * scale
        height = info.height * scale
        left = (page_width - width) / 2
        top = (page_height - height) / 2
        return page_width, page_height, pymupdf.Rect(left, top, left + width, top + height)

    dpi_x, dpi_y = info.dpi or (_DEFAULT_DPI, _DEFAULT_DPI)
    width = info.width * 72.0 / dpi_x
    height = info.height * 72.0 / dpi_y
    shrink = min(1.0, _MAX_PAGE_PT / max(width, height))
    width = max(width * shrink, _MIN_PAGE_PT)
    height = max(height * shrink, _MIN_PAGE_PT)
    return width, height, pymupdf.Rect(0, 0, width, height)


def _insert_image(page: pymupdf.Page, rect: pymupdf.Rect, source: Path) -> None:
    """Place the image file on the page, filling exactly `rect`.

    The bytes are read here so no file handle outlives this call, and
    keep_proportion is off because `rect` already has the right shape.
    """
    page.insert_image(rect, stream=source.read_bytes(), keep_proportion=False)


def _add_page(
    document: pymupdf.Document,
    path: Path,
    info: _Info,
    position: int,
    work_dir: Path,
    page_size: PageSize,
) -> None:
    page_width, page_height, rect = _layout(info, page_size)
    page = document.new_page(width=page_width, height=page_height)

    if info.direct:
        try:
            _insert_image(page, rect, path)
        except Exception as exc:  # noqa: BLE001 - MuPDF may refuse what Pillow accepted; re-encode instead
            logger.info("Image %s was refused as is (%s); re-encoding it", position, exc)
        else:
            return
    _insert_image(page, rect, _normalise(path, info, position, work_dir))


# -- Inspecting and normalising images -----------------------------------------


def _orientation(image: Image.Image) -> int:
    """The EXIF orientation, 1 (upright) when absent or unreadable."""
    try:
        value = image.getexif().get(_ORIENTATION_TAG, 1)
    except Exception:  # noqa: BLE001 - damaged EXIF must not make a good image unusable
        return 1
    return value if isinstance(value, int) and 1 <= value <= 8 else 1


def _read_dpi(image: Image.Image, *, swap: bool) -> tuple[float, float] | None:
    """The image's DPI tag if it is plausible, else None."""
    raw = image.info.get("dpi")
    if not isinstance(raw, tuple | list) or len(raw) != 2:
        return None
    try:
        x, y = float(raw[0]), float(raw[1])
    except (TypeError, ValueError):
        return None
    if not all(_MIN_DPI <= value <= _MAX_DPI for value in (x, y)):
        return None
    return (y, x) if swap else (x, y)


def _read_info(image: Image.Image) -> tuple[_Info | None, str | None]:
    """Judge an opened image: (info, None) if usable, else (None, why)."""
    if image.format in _JPEG_FORMATS:
        jpeg = True
    elif image.format == "PNG":
        jpeg = False
    else:
        return None, _UNREADABLE

    width, height = image.size
    if width < 1 or height < 1:
        return None, _UNREADABLE
    if width * height > _MAX_IMAGE_PIXELS:
        return None, _TOO_MANY_PIXELS

    orientation = _orientation(image)
    sideways = orientation in _SIDEWAYS
    if sideways:
        width, height = height, width
    direct = (
        image.format == "JPEG"
        and image.mode in ("RGB", "L")
        and orientation == 1
    )
    info = _Info(
        jpeg=jpeg,
        width=width,
        height=height,
        dpi=_read_dpi(image, swap=sideways),
        direct=direct,
    )
    return info, None


def _inspect(path: Path, position: int) -> _Info:
    """Open one image, validate it and decide how it will be embedded.

    AppError is raised only after the with and except blocks have ended, so no
    traceback keeps a Pillow object (and on Windows an open file) alive.
    """
    info: _Info | None = None
    problem: str | None = None
    try:
        with Image.open(path) as image:
            info, problem = _read_info(image)
            if info is not None and info.direct:
                image.load()  # a truncated or damaged JPEG fails here
    except Image.DecompressionBombError:
        problem = _TOO_MANY_PIXELS
    except Exception as exc:  # noqa: BLE001 - Pillow raises many unrelated types for damaged files
        logger.info("Image %s could not be read: %s", position, exc)
        problem = _UNREADABLE

    if problem == _TOO_MANY_PIXELS:
        raise AppError(
            TOO_LARGE,
            f"Image {position} has too many pixels to process safely. "
            "Please use a smaller or lower-resolution image.",
        )
    if problem is not None or info is None:
        raise AppError(NOT_IMAGE, not_image_message(position))
    return info


def _has_alpha(image: Image.Image) -> bool:
    return image.mode in ("RGBA", "LA", "PA", "RGBa", "La") or "transparency" in image.info


def _flatten_on_white(image: Image.Image) -> Image.Image:
    rgba = image.convert("RGBA")
    background = Image.new("RGB", rgba.size, (255, 255, 255))
    background.paste(rgba, mask=rgba.getchannel("A"))
    return background


def _sixteen_bit_to_gray(image: Image.Image) -> Image.Image:
    """Scale 16-bit gray to 8-bit. Plain convert("L") would clip to white."""
    wide = image if image.mode == "I" else image.convert("I")
    return wide.point(lambda value: value * (1 / 256)).convert("L")


def _prepare(image: Image.Image) -> Image.Image:
    """An 8-bit RGB or grayscale image with no alpha and no EXIF rotation."""
    current = image
    if _orientation(current) > 1:
        current = ImageOps.exif_transpose(current)
    if _has_alpha(current):
        return _flatten_on_white(current)
    if current.mode in ("RGB", "L"):
        return current
    if current.mode in ("I;16", "I;16L", "I;16B", "I"):
        return _sixteen_bit_to_gray(current)
    if current.mode == "1":
        return current.convert("L")
    return current.convert("RGB")


def _save_normalised(image: Image.Image, destination: Path, jpeg: bool) -> None:
    if jpeg:
        image.save(destination, format="JPEG", quality=_JPEG_QUALITY)
    else:
        image.save(destination, format="PNG")


def _normalise(path: Path, info: _Info, position: int, work_dir: Path) -> Path:
    """Re-encode one image into the work folder and return the new file.

    JPEGs stay JPEG (quality 92); PNGs stay PNG, so nothing is made lossy that
    was lossless. A decoding failure means the file is not a usable image.
    """
    extension = "jpg" if info.jpeg else "png"
    destination = work_dir / f"{position:03d}.{extension}"
    unreadable = False
    with Image.open(path) as image:
        try:
            image.load()
            prepared = _prepare(image)
        except Exception as exc:  # noqa: BLE001 - Pillow raises many unrelated types for damaged files
            logger.info("Image %s could not be decoded: %s", position, exc)
            unreadable = True
        else:
            _save_normalised(prepared, destination, info.jpeg)
    if unreadable:
        raise AppError(NOT_IMAGE, not_image_message(position))
    return destination
