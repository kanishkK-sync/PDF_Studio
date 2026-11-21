"""Compare corresponding page numbers and stream a local review archive."""

import json
import unicodedata
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path
from zipfile import ZIP_STORED, ZipFile

import pymupdf
from PIL import Image, ImageChops

from app.core.config import get_settings
from app.schemas.jobs import CompareStats
from app.services.pdf_common import GLOBAL_GATE, fit_render_dpi, open_pdf_document

PAGE_LIMIT = 25
# Several RGB images and single-channel masks coexist for one comparison.
CANVAS_PIXEL_LIMIT = 4_000_000
CYAN = (0, 235, 255)
MAGENTA = (255, 32, 165)


def _lines(page: pymupdf.Page | None) -> list[str]:
    if page is None:
        return []
    text = unicodedata.normalize("NFKC", page.get_text("text", sort=True))
    return [line for raw in text.splitlines() if (line := " ".join(raw.split()))]


def _text_changes(
    before: list[str], after: list[str]
) -> tuple[list[str], list[str], float]:
    if before == after:
        return [], [], 100.0
    # Match lines in reading order. Bound worst-case sequence matching on
    # unusually dense pages by using occurrence counts on the fallback path.
    if len(before) * len(after) <= 2_000_000:
        added, removed = [], []
        for tag, a, b, c, d in SequenceMatcher(None, before, after).get_opcodes():
            if tag != "equal":
                removed.extend(before[a:b])
                added.extend(after[c:d])
    else:
        old, new = Counter(before), Counter(after)
        removed = list((old - new).elements())
        added = list((new - old).elements())

    def word_pairs(lines):
        words = " ".join(lines).split()
        return Counter(zip([None, *words], [*words, None], strict=True))

    old_words, new_words = word_pairs(before), word_pairs(after)
    overlap = (old_words & new_words).total()
    similarity = 200 * overlap / (old_words.total() + new_words.total())
    return added, removed, similarity


def _render(
    page: pymupdf.Page | None, dpi: int, size: tuple[int, int]
) -> tuple[Image.Image, tuple[int, int]]:
    image = Image.new("RGB", size, "white")
    if page is None:
        return image, (0, 0)
    pix = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csRGB, alpha=False)
    with Image.frombytes("RGB", (pix.width, pix.height), pix.samples_mv) as pixels:
        image.paste(pixels)
        return image, pixels.size


def _write_overlay(
    original: pymupdf.Page | None,
    revised: pymupdf.Page | None,
    archive: ZipFile,
    name: str,
) -> tuple[int, int, float]:
    pages = [page for page in (original, revised) if page is not None]
    bounds = pymupdf.Rect(
        0, 0, max(p.rect.width for p in pages), max(p.rect.height for p in pages)
    )
    dpi = fit_render_dpi(
        bounds, 120, min(get_settings().max_render_pixels, CANVAS_PIXEL_LIMIT)
    )
    canvas = (bounds * pymupdf.Matrix(dpi / 72, dpi / 72)).irect
    size = (canvas.width, canvas.height)
    before, old_size = _render(original, dpi, size)
    try:
        after, new_size = _render(revised, dpi, size)
        with after:
            old_gray = before.convert("L")
            new_gray = after.convert("L")
            # Any RGB channel changing counts, including equal-luminance colors.
            with ImageChops.difference(before, after) as diff:
                red, green, blue = diff.split()
                changed = ImageChops.lighter(
                    ImageChops.lighter(red, green), blue
                ).point(lambda value: 255 if value else 0)
            removed = ImageChops.subtract(new_gray, old_gray).point(
                lambda value: 255 if value else 0
            )
            overlay = new_gray.point(lambda value: 25 + value * 0.40).convert("RGB")
            # Indicate the paper footprint too. This makes a blank inserted page
            # and size changes visible while keeping ink legible on top of it.
            mask = changed
            if old_size != new_size:
                old_paper, new_paper = Image.new("L", size), Image.new("L", size)
                old_paper.paste(255, (0, 0, *old_size))
                new_paper.paste(255, (0, 0, *new_size))
                overlay.paste(
                    (85, 10, 55), mask=ImageChops.subtract(old_paper, new_paper)
                )
                overlay.paste(
                    (0, 78, 85), mask=ImageChops.subtract(new_paper, old_paper)
                )
                mask = ImageChops.lighter(
                    changed, ImageChops.difference(old_paper, new_paper)
                )
            overlay.paste(CYAN, mask=changed)
            overlay.paste(MAGENTA, mask=removed)
            different = mask.histogram()[255]
            with archive.open(name, "w") as output:
                overlay.save(output, "PNG", compress_level=3)
            return (
                dpi,
                different,
                100 * (1 - different / (canvas.width * canvas.height)),
            )
    finally:
        before.close()


def compare_pdfs(original_path: Path, revised_path: Path, target: Path) -> CompareStats:
    with (
        GLOBAL_GATE.hold(),
        open_pdf_document(original_path) as old,
        open_pdf_document(revised_path) as new,
        ZipFile(target, "w", compression=ZIP_STORED) as archive,
    ):
        total = max(len(old), len(new))
        compared = min(total, PAGE_LIMIT, get_settings().max_pdf_pages)
        pages = []
        for index in range(compared):
            original = old[index] if index < len(old) else None
            revised = new[index] if index < len(new) else None
            name = f"page-{index + 1:03d}-diff.png"
            dpi, pixel_changes, pixel_score = _write_overlay(
                original, revised, archive, name
            )
            before, after = _lines(original), _lines(revised)
            added, removed, text_score = _text_changes(before, after)
            visual = bool(
                pixel_changes
                or original is None
                or revised is None
                or original.rect != revised.rect
            )
            if original is None:
                status = "added"
            elif revised is None:
                status = "removed"
            elif visual or before != after:
                status = "modified"
            else:
                status = "unchanged"
            score = round(min(pixel_score, text_score), 2)
            if status in ("added", "removed"):
                score = 0.0
            elif status == "modified":
                score = min(score, 99.99)
            pages.append(
                {
                    "page": index + 1,
                    "status": status,
                    "image": name,
                    "dpi": dpi,
                    "added_lines": added,
                    "removed_lines": removed,
                    "has_visual_changes": visual,
                    "similarity_percent": score,
                }
            )

        changed = sum(p["status"] != "unchanged" for p in pages)
        average = round(sum(p["similarity_percent"] for p in pages) / compared, 2)
        stats = CompareStats(
            original_pages=len(old),
            revised_pages=len(new),
            total_pages=total,
            compared_pages=compared,
            truncated=total > compared,
            pages_changed=changed,
            overall_similarity=min(99.99, average) if changed else 100,
        )
        archive.writestr(
            "diff-report.json",
            json.dumps(
                {**stats.model_dump(), "pages": pages}, ensure_ascii=False
            ).encode("utf-8"),
        )
        summary = [
            f"Compared {compared} of {total} page positions in page-number order.",
            f"Original: {len(old)} pages. Revised: {len(new)} pages.",
            f"Changed pages: {changed}. Overall similarity: {stats.overall_similarity}%.",
            "Cyan: added or darker. Magenta: removed or lighter. Gray: unchanged.",
            "",
        ]
        summary.extend(
            f"Page {p['page']}: {p['status']}, {p['similarity_percent']}% similarity"
            for p in pages
        )
        archive.writestr("diff-summary.txt", "\n".join(summary) + "\n")
        return stats
