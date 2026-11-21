"""Replace occurrences of selectable text in a PDF."""

import logging
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from app.core.config import get_settings
from app.core.errors import (
    NO_MATCH,
    NO_TEXT,
    PROCESSING_FAILED,
    TOO_MANY_PAGES,
    AppError,
)
from app.services.pdf_common import GLOBAL_GATE, open_pdf_document

logger = logging.getLogger(__name__)
RESULT_NAME = "result.pdf"
_gate = GLOBAL_GATE
rebuild_concurrency_gate = _gate.rebuild


@dataclass(frozen=True)
class EditResult:
    page_count: int
    replacement_count: int
    result_size: int
    result_name: str = RESULT_NAME


def edit_pdf(
    input_path: Path, output_dir: Path, old_text: str, new_text: str
) -> EditResult:
    """Redact exact matches and place replacement text in their rectangles."""
    try:
        with _gate.hold():
            document = open_pdf_document(input_path)
            try:
                if document.page_count > get_settings().max_pdf_pages:
                    raise AppError(TOO_MANY_PAGES)
                count = 0
                has_text = False
                for page in document:
                    has_text = has_text or bool(page.get_text().strip())
                    matches = page.search_for(old_text)
                    if not matches:
                        continue
                    count += len(matches)
                    for rect in matches:
                        page.add_redact_annot(rect, text=new_text, fontsize=8, fill=(1, 1, 1))
                    page.apply_redactions(images=0, graphics=0)
                if count == 0:
                    raise AppError(NO_MATCH if has_text else NO_TEXT)
                with tempfile.NamedTemporaryFile(
                    suffix=".pdf", dir=output_dir, delete=False
                ) as temp:
                    staged = Path(temp.name)
                try:
                    document.save(str(staged), garbage=4, deflate=True)
                    os.replace(staged, output_dir / RESULT_NAME)
                finally:
                    staged.unlink(missing_ok=True)
                return EditResult(
                    document.page_count,
                    count,
                    (output_dir / RESULT_NAME).stat().st_size,
                )
            finally:
                document.close()
    except AppError:
        raise
    except Exception as exc:
        logger.exception("PDF text replacement failed")
        raise AppError(PROCESSING_FAILED, "We couldn't edit this PDF. Please try again.") from exc
