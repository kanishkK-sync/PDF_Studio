"""Remove matching page content and verify the saved PDF before publication."""

import re
from collections import defaultdict
from pathlib import Path

import pymupdf

from app.core.config import get_settings
from app.core.errors import (
    INVALID_REQUEST,
    NO_MATCHES,
    PROCESSING_FAILED,
    TOO_MANY_PAGES,
    AppError,
)
from app.services.pdf_common import GLOBAL_GATE, open_pdf_document

PRESETS = {
    "emails": r"(?<![\w.+%-])[\w.+%-]+@[\w.-]+\.[A-Z]{2,}",
    "phones": r"(?<!\d)(?:\+\d{1,3}[-. ]?)?(?:\(\d{2,4}\)|\d{3})[-. ]?\d{3}[-. ]?\d{4}(?!\d)",
    "ssn": r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)",
    "cards": r"(?<!\d)(?:\d{13,19}|\d{4}([ -])\d{4}\1\d{4}\1\d{1,7}|\d{4}[ -]\d{6}[ -]\d{5})(?!\d)",
    "urls": r"(?:https?://|www\.)[^\s<>]+",
}


def patterns(terms: str, presets: str) -> list[re.Pattern]:
    literals = {s.strip() for s in re.split(r"[,\n]", terms) if s.strip()}
    names = {s.strip().lower() for s in presets.split(",") if s.strip()}
    if names - PRESETS.keys() or not (names or literals):
        raise AppError(
            INVALID_REQUEST, "Choose a preset or enter a sensitive phrase.", 400
        )
    if len(terms) > 8000 or len(literals) > 100:
        raise AppError(
            INVALID_REQUEST, "Use at most 100 phrases and 8000 characters.", 400
        )
    # Capture overlapping literal occurrences as well ("ana" twice in "banana").
    expressions = [r"\s+".join(re.escape(w) for w in s.split()) for s in literals]
    return [re.compile(f"(?=(?P<phrase>{p}))", re.IGNORECASE) for p in expressions] + [
        re.compile(PRESETS[n], re.IGNORECASE) for n in names
    ]


def find_matches(page, rules, flags):
    # Map each character to its original line and box. A wrapped phrase needs
    # one rectangle per line, without blacking out the space between columns.
    text, locations = [], []
    raw = page.get_text("rawdict", flags=flags, clip=pymupdf.INFINITE_RECT())
    for block in raw["blocks"]:
        for line in block["lines"]:
            line_id = len(text)
            for span in line["spans"]:
                for char in span["chars"]:
                    for letter in char["c"]:
                        text.append(letter)
                        locations.append((line_id, char["bbox"]))
            text.append("\n")
            locations.append(None)
    content = "".join(text)
    spans = {
        m.span("phrase") if "phrase" in rule.groupindex else m.span()
        for rule in rules
        for m in rule.finditer(content)
    }
    unmatched = []
    matches = []
    cursor = 0
    for start, end in sorted(spans):
        if start > cursor:
            unmatched.append(content[cursor:start])
        cursor = max(cursor, end)
        boxes = defaultdict(pymupdf.Rect)
        for location in locations[start:end]:
            if location:
                line_id, rect = location
                boxes[line_id] |= pymupdf.Rect(rect)
        matches.append(list(boxes.values()))
    unmatched.append(content[cursor:])
    return matches, "".join("".join(unmatched).split())


def scan_page(page, rules):
    # Tagged PDFs can substitute accessibility text for their painted glyphs.
    # Inspect both views, counting identical locations just once.
    flags = (
        pymupdf.TEXTFLAGS_TEXT
        & ~pymupdf.TEXT_PRESERVE_LIGATURES
        & ~pymupdf.TEXT_MEDIABOX_CLIP
    )
    rectangles = {}
    unmatched_text = []
    for view in (flags, flags | pymupdf.TEXT_IGNORE_ACTUALTEXT):
        matches, unmatched = find_matches(page, rules, view)
        unmatched_text.append(unmatched)
        for boxes in matches:
            location = tuple(tuple(box) for box in boxes)
            rectangles[location] = boxes
    return rectangles.values(), unmatched_text


def contains_only_unmatched_text(actual, expected):
    # Rewriting a PDF can shift neighboring glyphs or remove touching
    # content. Every surviving character must still be accounted for in order.
    remaining = iter(expected)
    return all(char in remaining for char in actual)


def redact_pdf(
    source: Path, target: Path, terms: str, presets: str, scrub: bool
) -> int:
    rules = patterns(terms, presets)
    count = 0
    unmatched_pages = []
    with GLOBAL_GATE.hold(), open_pdf_document(source) as doc:
        if doc.page_count > get_settings().max_pdf_pages:
            raise AppError(TOO_MANY_PAGES)
        for page in doc:
            matches, unmatched = scan_page(page, rules)
            areas = [box for boxes in matches for box in boxes]
            unmatched_pages.append(unmatched)
            for box in areas:
                page.add_redact_annot(box, fill=(0, 0, 0))
            # Removing an existing redaction annotation before applying it would
            # reveal the material its author had already marked for removal.
            if matches or (
                scrub and any(page.annots(types=[pymupdf.PDF_ANNOT_REDACT]))
            ):
                page.apply_redactions(
                    images=pymupdf.PDF_REDACT_IMAGE_PIXELS,
                    graphics=pymupdf.PDF_REDACT_LINE_ART_REMOVE_IF_TOUCHED,
                )
            count += len(matches)
        if not count and not scrub:
            raise AppError(NO_MATCHES)
        if scrub:
            # Copy only page content into a fresh catalog. Drop forms, outlines,
            # annotations, links, attachments and document-level actions.
            with pymupdf.open() as clean:
                clean.insert_pdf(doc, links=False, annots=False, widgets=False)
                clean.scrub(hidden_text=False)
                clean.set_metadata({})
                clean.del_xml_metadata()
                clean.save(target, garbage=4, clean=True, deflate=True)
        else:
            doc.save(target, garbage=4, clean=True, deflate=True)
        with pymupdf.open(target) as saved:
            for page, expected in zip(saved, unmatched_pages, strict=True):
                matches, actual = scan_page(page, rules)
                if matches:
                    raise AppError(
                        PROCESSING_FAILED,
                        "Verification found matching text in the output.",
                    )
                # A partial deletion would defeat a phrase search while leaving
                # some characters recoverable. Also compare the remaining text.
                if not all(
                    contains_only_unmatched_text(a, e)
                    for a, e in zip(actual, expected, strict=True)
                ):
                    raise AppError(
                        PROCESSING_FAILED, "Text remains in a redacted area."
                    )
    return count
