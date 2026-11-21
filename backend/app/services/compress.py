"""PDF compression engine.

Pipeline for one job:

1. Open the input with PyMuPDF and classify it (encrypted, corrupt) while
   recording a fingerprint: page count, page sizes, bookmark count and the
   text of the first pages.
2. Build candidate files inside a private work folder:
   - a lossless candidate (PyMuPDF save options, then a pikepdf structural
     pass) for every level;
   - for balanced and strong, an image candidate where eligible images are
     resampled and re-encoded as JPEG, followed by the same structural pass.
3. Throw away any candidate that is not smaller than the input, then validate
   the rest from smallest to largest by reopening them and comparing them with
   the fingerprint. The first one that validates wins.
4. If nothing wins, the result is a byte copy of the input.

Pages are never rasterized, so text stays selectable and searchable.
Only logs (server side) ever mention why a fallback happened; AppError
messages stay friendly and free of paths or exception text.
"""

import io
import logging
import math
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import get_args

import pikepdf
import pymupdf
from PIL import Image

from app.core.errors import (
    CORRUPT,
    INVALID_LEVEL,
    PROCESSING_FAILED,
    AppError,
)
from app.schemas.jobs import Level
from app.services.pdf_common import GLOBAL_GATE, open_pdf_document

logger = logging.getLogger(__name__)

RESULT_NAME = "result.pdf"

_WORK_PREFIX = ".work-"
_TEXT_PAGES = 5
_MIN_IMAGE_SIDE = 64
_MAX_IMAGE_PIXELS = 60_000_000  # above this, decoding costs too much memory
_UNSUPPORTED_FILTERS = ("JPXDecode", "JBIG2Decode", "CCITTFaxDecode")
_UNSUPPORTED_COLORSPACES = ("Separation", "DeviceN", "Lab", "CMYK", "Pattern")
_NO_IMAGES: frozenset[tuple[int, int]] = frozenset()

# Richest option set first. PyMuPDF's save() has named parameters, so an option
# this version does not know raises TypeError and we fall back to the next set.
_SAVE_OPTION_SETS: tuple[dict[str, bool | int], ...] = (
    {
        "garbage": 4,
        "deflate": True,
        "deflate_images": True,
        "deflate_fonts": True,
        "use_objstms": 1,
    },
    {"garbage": 4, "deflate": True},
)


@dataclass(frozen=True)
class CompressionResult:
    """What the caller needs to build a response."""

    original_size: int
    compressed_size: int
    already_optimized: bool
    page_count: int


@dataclass(frozen=True)
class _ImagePolicy:
    """Resample images above `threshold_dpi` down to `target_dpi`; JPEG quality."""

    threshold_dpi: int
    target_dpi: int
    quality: int


_POLICIES: dict[str, _ImagePolicy] = {
    "balanced": _ImagePolicy(threshold_dpi=170, target_dpi=150, quality=75),
    "strong": _ImagePolicy(threshold_dpi=120, target_dpi=100, quality=55),
}


@dataclass(frozen=True)
class _Fingerprint:
    page_count: int
    page_sizes: tuple[tuple[float, float], ...]
    bookmark_count: int
    texts: tuple[str, ...]


@dataclass(frozen=True)
class _Candidate:
    """A finished candidate file and the sizes of the images it re-encoded."""

    path: Path
    replaced_dims: frozenset[tuple[int, int]]


@dataclass(frozen=True)
class _ImageInfo:
    xref: int
    smask: int
    width: int
    height: int
    bpc: int


@dataclass(frozen=True)
class _Encoded:
    data: bytes
    width: int
    height: int
    gray: bool


class _ImageCandidateError(Exception):
    """Writing a re-encoded image into the document failed; drop the candidate."""


# -- Concurrency ---------------------------------------------------------------

rebuild_concurrency_gate = GLOBAL_GATE.rebuild


# -- Public API ----------------------------------------------------------------


def parse_level(raw: object) -> Level:
    """Return the level if `raw` is exactly light, balanced or strong.

    Raises invalid_level for anything else, including None.
    """
    for level in get_args(Level):
        if raw == level:
            return level
    raise AppError(INVALID_LEVEL)


def compress_pdf(input_path: Path, output_path: Path, level: Level) -> CompressionResult:
    """Compress `input_path` into `output_path` and describe the outcome.

    Blocking and CPU heavy: call it from a worker thread. The concurrency gate
    is acquired here, inside that thread, so waiting jobs never block the event
    loop. Every failure leaves as an AppError.
    """
    parse_level(level)
    try:
        with GLOBAL_GATE.hold():
            return _compress_locked(input_path, output_path, level)
    except AppError:
        raise
    except Exception as exc:
        # PyMuPDF, pikepdf and Pillow raise many unrelated types; the client
        # only ever needs to know that processing failed.
        logger.exception("Compression failed unexpectedly")
        raise AppError(PROCESSING_FAILED) from exc


# -- Orchestration -------------------------------------------------------------


def _compress_locked(
    input_path: Path, output_path: Path, level: Level
) -> CompressionResult:
    original_size = input_path.stat().st_size
    expected = _open_and_fingerprint(input_path)

    # Inside the job's output folder so the sweeper also covers leftovers.
    work_dir = Path(tempfile.mkdtemp(prefix=_WORK_PREFIX, dir=output_path.parent))
    try:
        candidates = _collect_candidates(input_path, work_dir, level)
        chosen = _choose_candidate(candidates, original_size, expected)
        if chosen is None:
            shutil.copyfile(input_path, output_path)
            return CompressionResult(
                original_size=original_size,
                compressed_size=original_size,
                already_optimized=True,
                page_count=expected.page_count,
            )
        compressed_size = chosen.path.stat().st_size
        os.replace(chosen.path, output_path)
        return CompressionResult(
            original_size=original_size,
            compressed_size=compressed_size,
            already_optimized=False,
            page_count=expected.page_count,
        )
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def _normalise(text: str) -> str:
    return " ".join(text.split())


def _bookmark_count(document: pymupdf.Document) -> int:
    try:
        return len(document.get_toc())
    except Exception:  # noqa: BLE001 - an odd outline must not make a readable PDF unusable
        return -1


def _fingerprint(document: pymupdf.Document) -> _Fingerprint:
    sizes: list[tuple[float, float]] = []
    for index in range(document.page_count):
        rect = document.load_page(index).rect
        sizes.append((round(rect.width, 2), round(rect.height, 2)))
    texts = tuple(
        _normalise(document.load_page(index).get_text("text"))
        for index in range(min(_TEXT_PAGES, document.page_count))
    )
    return _Fingerprint(
        page_count=document.page_count,
        page_sizes=tuple(sizes),
        bookmark_count=_bookmark_count(document),
        texts=texts,
    )


def _open_and_fingerprint(path: Path) -> _Fingerprint:
    """Classify the input with the shared guard and fingerprint it."""
    document = open_pdf_document(path)
    try:
        try:
            return _fingerprint(document)
        except Exception as exc:
            logger.info("Input could not be read: %s", exc)
            raise AppError(CORRUPT) from exc
    finally:
        document.close()


# -- Candidates ----------------------------------------------------------------


def _collect_candidates(
    input_path: Path, work_dir: Path, level: Level
) -> list[_Candidate]:
    """Build every candidate this level allows. Failures are logged, not raised."""
    candidates: list[_Candidate] = []

    lossless = work_dir / "lossless.pdf"
    try:
        _save_lossless(input_path, lossless)
    except Exception:
        logger.exception("Lossless candidate could not be built")
    else:
        candidates.append(_Candidate(lossless, _NO_IMAGES))
        _append_structural(
            candidates, lossless, work_dir / "lossless-structural.pdf", _NO_IMAGES
        )

    policy = _POLICIES.get(level)
    if policy is None:
        return candidates

    images = work_dir / "images.pdf"
    try:
        replaced = _build_image_candidate(input_path, images, policy)
    except Exception:
        logger.exception("Image candidate could not be built; using lossless only")
        return candidates
    if not replaced:
        logger.info("No image qualified for recompression")
        return candidates
    candidates.append(_Candidate(images, replaced))
    _append_structural(
        candidates, images, work_dir / "images-structural.pdf", replaced
    )
    return candidates


def _append_structural(
    candidates: list[_Candidate],
    source: Path,
    destination: Path,
    replaced: frozenset[tuple[int, int]],
) -> None:
    if _structural_pass(source, destination):
        candidates.append(_Candidate(destination, replaced))


def _save_document(document: pymupdf.Document, destination: Path) -> None:
    """Save with the strongest option set this PyMuPDF version accepts."""
    last_index = len(_SAVE_OPTION_SETS) - 1
    for index, options in enumerate(_SAVE_OPTION_SETS):
        try:
            document.save(str(destination), **options)
        except (TypeError, ValueError):
            destination.unlink(missing_ok=True)
            if index == last_index:
                raise
            logger.info("Save options %s were rejected; trying simpler ones", options)
        else:
            return


def _save_lossless(source: Path, destination: Path) -> None:
    document = pymupdf.open(str(source))
    try:
        _save_document(document, destination)
    finally:
        document.close()


def _structural_pass(source: Path, destination: Path) -> bool:
    """Rewrite `source` with pikepdf (recompressed streams, object streams).

    Returns False, leaving nothing behind, if pikepdf cannot open or save it;
    the PyMuPDF result then stays the candidate.
    """
    try:
        with pikepdf.open(source) as pdf:
            pdf.save(
                destination,
                compress_streams=True,
                recompress_flate=True,
                object_stream_mode=pikepdf.ObjectStreamMode.generate,
            )
    except Exception as exc:  # noqa: BLE001 - pikepdf has its own hierarchy plus OSError/ValueError
        logger.info("Structural pass skipped: %s", exc)
        destination.unlink(missing_ok=True)
        return False
    return True


# -- Image rewriting -----------------------------------------------------------


def _build_image_candidate(
    source: Path, destination: Path, policy: _ImagePolicy
) -> frozenset[tuple[int, int]]:
    """Re-encode eligible images and save. Returns the new (width, height) set.

    An empty set means nothing was replaced and no file was written.
    """
    document = pymupdf.open(str(source))
    try:
        replaced = _rewrite_images(document, policy)
        if not replaced:
            return _NO_IMAGES
        _save_document(document, destination)
        return replaced
    finally:
        document.close()


def _effective_dpi(width: int, height: int, rect: pymupdf.Rect) -> float | None:
    """Pixels per inch, from the pixel area over the placed area.

    The area form does not care whether the image is rotated by 90 degrees.
    """
    inches = (rect.width / 72.0) * (rect.height / 72.0)
    if not math.isfinite(inches) or inches <= 0:
        return None
    return math.sqrt((width * height) / inches)


def _rewrite_images(
    document: pymupdf.Document, policy: _ImagePolicy
) -> frozenset[tuple[int, int]]:
    """Re-encode eligible images in place; return the new sizes of those changed."""
    infos: dict[int, _ImageInfo] = {}
    min_dpi: dict[int, float] = {}
    unsafe: set[int] = set()

    for page_index in range(document.page_count):
        page = document.load_page(page_index)
        for item in page.get_images(full=True):
            xref = int(item[0])
            if xref not in infos:
                infos[xref] = _ImageInfo(
                    xref=xref,
                    smask=int(item[1]),
                    width=int(item[2]),
                    height=int(item[3]),
                    bpc=int(item[4]),
                )
            try:
                rects = page.get_image_rects(xref)
            except Exception:  # noqa: BLE001 - unknown placement just means "leave this image alone"
                rects = []
            if not rects:
                # Placement unknown (e.g. drawn from a form XObject): leave it.
                unsafe.add(xref)
                continue
            info = infos[xref]
            for rect in rects:
                dpi = _effective_dpi(info.width, info.height, rect)
                if dpi is None:
                    unsafe.add(xref)
                    break
                # The largest placement has the lowest dpi; never go below
                # the target for it.
                min_dpi[xref] = min(min_dpi.get(xref, dpi), dpi)

    replaced: set[tuple[int, int]] = set()
    for xref, info in infos.items():
        if xref in unsafe or xref not in min_dpi:
            continue
        if not _is_eligible(document, info):
            continue
        outcome = _recompress_image(document, info, min_dpi[xref], policy)
        if outcome is not None:
            replaced.add(outcome)
    return frozenset(replaced)


def _key_value(document: pymupdf.Document, xref: int, key: str) -> str:
    """The raw value of a key in an object dictionary, or "" if it is absent."""
    kind, value = document.xref_get_key(xref, key)
    return "" if kind == "null" else str(value)


def _colorspace_text(document: pymupdf.Document, xref: int) -> str:
    kind, value = document.xref_get_key(xref, "ColorSpace")
    if kind == "null":
        return ""
    if kind == "xref":
        try:
            return str(document.xref_object(int(str(value).split()[0])))
        except (ValueError, RuntimeError):
            return str(value)
    return str(value)


def _is_eligible(document: pymupdf.Document, info: _ImageInfo) -> bool:
    """Exclude everything we cannot re-encode without changing how it renders."""
    if info.smask:
        return False
    if min(info.width, info.height) < _MIN_IMAGE_SIDE:
        return False
    if info.width * info.height > _MAX_IMAGE_PIXELS:
        return False
    if info.bpc == 1 or info.bpc > 8:
        return False
    for key in ("Mask", "SMask", "Decode"):
        if _key_value(document, info.xref, key):
            return False
    if _key_value(document, info.xref, "ImageMask") == "true":
        return False
    filters = _key_value(document, info.xref, "Filter")
    if any(name in filters for name in _UNSUPPORTED_FILTERS):
        return False
    colorspace = _colorspace_text(document, info.xref)
    return not any(name in colorspace for name in _UNSUPPORTED_COLORSPACES)


def _pillow_mode(pixmap: pymupdf.Pixmap) -> str | None:
    if pixmap.alpha or pixmap.colorspace is None:
        return None
    if "lab" in pixmap.colorspace.name.lower():
        return None
    if pixmap.n == 1:
        return "L"
    if pixmap.n == 3:
        return "RGB"
    return None


def _encode_image(
    document: pymupdf.Document, info: _ImageInfo, dpi: float, policy: _ImagePolicy
) -> _Encoded | None:
    """Decode, optionally resample, and JPEG-encode one image. None means skip it.

    Any failure here only skips this image; the document is untouched.
    """
    resample = dpi > policy.threshold_dpi
    if not resample and "DCTDecode" in _key_value(document, info.xref, "Filter"):
        return None  # an unresized JPEG would only lose quality for a tiny gain
    try:
        pixmap = pymupdf.Pixmap(document, info.xref)
        try:
            mode = _pillow_mode(pixmap)
            if mode is None:
                return None
            width, height = pixmap.width, pixmap.height
            image = Image.frombuffer(
                mode, (width, height), pixmap.samples, "raw", mode, pixmap.stride, 1
            )
        finally:
            del pixmap
        try:
            if resample:
                scale = policy.target_dpi / dpi
                new_size = (max(1, round(width * scale)), max(1, round(height * scale)))
                resized = image.resize(new_size, Image.Resampling.LANCZOS)
                image.close()
                image = resized
            with io.BytesIO() as buffer:
                image.save(buffer, format="JPEG", quality=policy.quality, optimize=True)
                return _Encoded(
                    data=buffer.getvalue(),
                    width=image.width,
                    height=image.height,
                    gray=mode == "L",
                )
        finally:
            image.close()
    except Exception as exc:  # noqa: BLE001 - one odd image must not sink the whole job
        logger.info("Image %s skipped: %s", info.xref, exc)
        return None


def _recompress_image(
    document: pymupdf.Document, info: _ImageInfo, dpi: float, policy: _ImagePolicy
) -> tuple[int, int] | None:
    """Replace one image if the new encoding is smaller. Returns its new size."""
    encoded = _encode_image(document, info, dpi, policy)
    if encoded is None:
        return None
    original = document.xref_stream_raw(info.xref)
    if original is None or len(encoded.data) >= len(original):
        return None  # keep the original whenever the new encoding is not smaller
    try:
        # update_stream stores the bytes as given; the dictionary keys that
        # describe them are set afterwards.
        document.update_stream(info.xref, encoded.data, new=False, compress=False)
        document.xref_set_key(info.xref, "Filter", "/DCTDecode")
        document.xref_set_key(info.xref, "DecodeParms", "null")
        document.xref_set_key(info.xref, "Width", str(encoded.width))
        document.xref_set_key(info.xref, "Height", str(encoded.height))
        document.xref_set_key(
            info.xref,
            "ColorSpace",
            "/DeviceGray" if encoded.gray else "/DeviceRGB",
        )
        document.xref_set_key(info.xref, "BitsPerComponent", "8")
    except Exception as exc:
        raise _ImageCandidateError from exc
    return (encoded.width, encoded.height)


# -- Validation and choice -----------------------------------------------------


def _replaced_images_decode(
    document: pymupdf.Document, dims: frozenset[tuple[int, int]]
) -> bool:
    """Decode every image whose size matches a re-encoded one.

    Object numbers change when the file is saved with garbage collection, so
    images are found again by size instead of by number.
    """
    if not dims:
        return True
    checked: set[int] = set()
    for page_index in range(document.page_count):
        for item in document.load_page(page_index).get_images(full=True):
            xref, width, height = int(item[0]), int(item[2]), int(item[3])
            if xref in checked or (width, height) not in dims:
                continue
            checked.add(xref)
            pixmap = pymupdf.Pixmap(document, xref)
            try:
                matches = (pixmap.width, pixmap.height) == (width, height)
            finally:
                del pixmap
            if not matches:
                return False
    return True


def _validate_candidate(
    path: Path, expected: _Fingerprint, dims: frozenset[tuple[int, int]]
) -> str | None:
    """Reopen a candidate and compare it with the input. None means it is valid."""
    try:
        document = pymupdf.open(str(path))
    except Exception:  # noqa: BLE001 - any failure to reopen rejects the candidate
        return "could not be reopened"
    try:
        if document.needs_pass or document.is_encrypted:
            return "became encrypted"
        if document.page_count != expected.page_count:
            return "page count changed"
        found = _fingerprint(document)
        if found.page_sizes != expected.page_sizes:
            return "page sizes changed"
        if found.bookmark_count != expected.bookmark_count:
            return "bookmark count changed"
        if found.texts != expected.texts:
            return "extracted text changed"
        if not _replaced_images_decode(document, dims):
            return "a re-encoded image does not decode"
        return None
    except Exception as exc:  # noqa: BLE001 - any error while checking rejects the candidate
        return f"validation raised {type(exc).__name__}"
    finally:
        document.close()


def _choose_candidate(
    candidates: list[_Candidate], original_size: int, expected: _Fingerprint
) -> _Candidate | None:
    """The smallest candidate that is smaller than the input and validates."""
    sized: list[tuple[int, _Candidate]] = []
    for candidate in candidates:
        try:
            size = candidate.path.stat().st_size
        except OSError:
            continue
        if size < original_size:
            sized.append((size, candidate))
    sized.sort(key=lambda pair: pair[0])

    if not sized:
        logger.info("No candidate was smaller than the input; returning the original")
        return None
    for _size, candidate in sized:
        reason = _validate_candidate(candidate.path, expected, candidate.replaced_dims)
        if reason is None:
            return candidate
        logger.warning("Candidate %s rejected: %s", candidate.path.name, reason)
    logger.warning("No candidate validated; returning the original")
    return None
