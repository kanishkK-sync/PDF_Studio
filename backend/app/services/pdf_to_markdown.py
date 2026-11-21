"""Extract GFM text, using page geometry to order columns and tables."""

import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import pymupdf

from app.core.config import get_settings
from app.core.errors import NO_CONTENT, TOO_MANY_PAGES, AppError
from app.services.pdf_common import GLOBAL_GATE, open_pdf_document


@dataclass
class Item:
    box: pymupdf.Rect
    text: str
    size: float = 0
    edge: str = ""
    paragraph: int = -1


def pipe_table(rows):
    if not rows:
        return ""
    # Some detected grids include a completely empty spacer column.
    columns = [
        i
        for i in range(max(map(len, rows)))
        if any(i < len(row) and (row[i] or "").strip() for row in rows)
    ]
    if not columns:
        return ""

    def row(values):
        cells = [
            (v or "").replace("\\", "\\\\").replace("|", "\\|").replace("\n", "<br>")
            for v in values
        ]
        return (
            "| "
            + " | ".join(cells[i] if i < len(cells) else "" for i in columns)
            + " |"
        )

    divider = "| " + " | ".join(["---"] * len(columns)) + " |"
    return "\n".join([row(rows[0]), divider, *(row(v) for v in rows[1:])])


def extract(page):
    items = []
    tables = []
    blocks = page.get_text("dict", flags=pymupdf.TEXTFLAGS_TEXT)["blocks"]
    if not blocks:
        return []
    finder = page.find_tables()
    for table in finder.tables if finder else ():
        body = pipe_table(table.extract())
        if body:
            box = pymupdf.Rect(table.bbox)
            tables.append(box)
            items.append(Item(box, body))
    bounds = page.rect * page.derotation_matrix
    for index, block in enumerate(blocks):
        for line in block["lines"]:
            box = pymupdf.Rect(line["bbox"])
            center = (box.tl + box.br) / 2
            if any(center in table for table in tables):
                continue
            spans = line["spans"]
            text = "".join(s["text"] for s in spans).strip()
            if not text:
                continue
            size = round(max(spans, key=lambda s: len(s["text"]))["size"], 1)
            edge = (
                "top"
                if box.y1 < bounds.height * 0.10
                else ("bottom" if box.y0 > bounds.height * 0.9 else "")
            )
            items.append(Item(box, text, size, edge, index))
    return items


def groups_along_axis(items, axis, gap):
    ordered = sorted(items, key=lambda item: item.box[axis])
    extent = ordered[0].box[axis + 2]
    groups = [[]]
    for item in ordered:
        if item.box[axis] > extent + gap:
            groups.append([])
        groups[-1].append(item)
        extent = max(extent, item.box[axis + 2])
    return groups


def reading_order(items):
    """Read complete columns between spanning headings, tables and footers."""
    if len(items) < 2:
        return items
    columns = groups_along_axis(items, 0, 14)
    if len(columns) > 1:
        # A right-aligned title above the body is a separate band, not a column.
        columns.sort(key=lambda col: min(i.box.y0 for i in col))
        bands = []
        bottom = float("-inf")
        for col in columns:
            if min(i.box.y0 for i in col) >= bottom:
                bands.append([])
            bands[-1].append(col)
            bottom = max(bottom, max(i.box.y1 for i in col))
        return [
            item
            for band in bands
            for col in sorted(band, key=lambda c: c[0].box.x0)
            for item in reading_order(col)
        ]
    rows = groups_along_axis(items, 1, 1)
    width = max(i.box.x1 for i in items) - min(i.box.x0 for i in items)
    # Split only at spanning bands. Splitting at every line of whitespace
    # would interleave the left and right columns underneath a wide title.
    if len(rows) > 1:
        sections, pending = [], []
        for row in rows:
            if any(i.box.width >= width * 0.65 for i in row):
                if pending:
                    sections.append(pending)
                    pending = []
                sections.append(row)
            else:
                pending.extend(row)
        if pending:
            sections.append(pending)
        if len(sections) > 1:
            return [item for section in sections for item in reading_order(section)]
    return sorted(items, key=lambda item: (item.box.y0, item.box.x0))


def edge_key(item):
    key = item.text.casefold()
    key = re.sub(r"\bpage\s+\d+|\b\d+\s+of\s+\d+|^\d+$", "#", key)
    return item.edge, key


def convert_pdf_to_markdown(source: Path, target: Path, markers: bool):
    with GLOBAL_GATE.hold(), open_pdf_document(source) as doc:
        if doc.page_count > get_settings().max_pdf_pages:
            raise AppError(TOO_MANY_PAGES)
        pages = [extract(page) for page in doc]
    edges = Counter(
        key for page in pages for key in {edge_key(i) for i in page if i.edge}
    )
    pages = [
        [
            i
            for i in page
            if not (i.edge and edges[edge_key(i)] >= max(2, len(pages) / 2))
        ]
        for page in pages
    ]
    sizes = Counter()
    for page in pages:
        for item in page:
            if item.size:
                sizes[item.size] += len(item.text)
    body = sizes.most_common(1)[0][0] if sizes else 12
    levels = sorted((s for s in sizes if s >= body * 1.15), reverse=True)
    sections = []
    words = 0
    for number, page in enumerate(pages, 1):
        lines = [f"<!-- Page {number} -->"] if markers else []
        previous_para = None
        for item in reading_order(page):
            text = item.text
            words += len(re.findall(r"\b[\w]+\b", text))
            if re.match(r"^[•◦▪●]\s*", text):
                text = re.sub(r"^[•◦▪●]\s*", "- ", text)
            is_list = re.match(r"^(?:[-*+]|\d+[.)])\s+", text)
            if is_list:
                text = re.sub(r"^(\d+)\)\s+", r"\1. ", text)
            elif item.size in levels:
                text = "#" * min(3, levels.index(item.size) + 1) + " " + text
            elif item.size and item.paragraph == previous_para:
                lines[-1] += " " + text
                continue
            if lines and not (is_list and previous_para == "list"):
                lines.append("")
            lines.append(text)
            previous_para = (
                "list"
                if is_list
                else (item.paragraph if item.size and item.size not in levels else None)
            )
        sections.append("\n".join(lines))
    if not any(pages):
        raise AppError(
            NO_CONTENT, "No extractable text was found. Scanned pages need OCR.", 400
        )
    markdown = "\n\n".join(sections).strip() + "\n"
    target.write_bytes(markdown.encode("utf-8"))
    return len(pages), words, (len(markdown) + 3) // 4, markdown
