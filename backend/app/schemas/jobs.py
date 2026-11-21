"""Shared types for compression jobs."""

from typing import Literal

from pydantic import BaseModel

Level = Literal["light", "balanced", "strong"]


class CompressResponse(BaseModel):
    """Payload returned by POST /api/compress."""

    job_id: str
    original_name: str
    original_size: int
    compressed_size: int
    saved_bytes: int
    saved_percent: float
    already_optimized: bool
    level: Level
    download_url: str


Quality = Literal["low", "medium", "high"]


class PdfToJpgResponse(BaseModel):
    """Payload returned by POST /api/pdf-to-jpg."""

    job_id: str
    original_name: str
    page_count: int
    file_count: int
    result_size: int
    kind: Literal["jpg", "zip"]
    quality: Quality
    download_url: str


PageSize = Literal["fit", "a4"]


class JpgToPdfResponse(BaseModel):
    """Payload returned by POST /api/jpg-to-pdf."""

    job_id: str
    page_count: int
    total_input_size: int
    result_size: int
    page_size: PageSize
    download_url: str

class PdfToWordResponse(BaseModel):
    """Payload returned by POST /api/pdf-to-word."""

    job_id: str
    original_name: str
    page_count: int
    original_size: int
    result_size: int
    download_name: str
    download_url: str


class PdfToExcelResponse(BaseModel):
    """Payload returned by POST /api/pdf-to-excel."""

    job_id: str
    original_name: str
    page_count: int
    table_count: int
    sheet_count: int
    mode: Literal["tables", "text"]
    original_size: int
    result_size: int
    download_name: str
    download_url: str


class PdfToPptxResponse(BaseModel):
    """Payload returned by POST /api/pdf-to-pptx."""

    job_id: str
    original_name: str
    page_count: int
    slide_count: int
    mode: Literal["pictures", "editable"]
    original_size: int
    result_size: int
    download_name: str
    download_url: str


class MergeResponse(BaseModel):
    """Payload returned by POST /api/merge."""

    job_id: str
    file_count: int
    page_count: int
    total_input_size: int
    result_size: int
    download_name: str
    download_url: str


SplitMode = Literal["extract", "separate"]
SplitKind = Literal["pdf", "zip"]


class SplitResponse(BaseModel):
    """Payload returned by POST /api/split."""

    job_id: str
    original_name: str
    page_count: int
    selected_pages: int
    file_count: int
    kind: SplitKind
    mode: SplitMode
    result_size: int
    download_name: str
    download_url: str


class OfficeToPdfResponse(BaseModel):
    """Payload returned by an Office to PDF route."""

    job_id: str
    original_name: str
    original_size: int
    result_size: int
    page_count: int
    download_name: str
    download_url: str


class EditPdfResponse(OfficeToPdfResponse):
    """Payload returned after replacing text in a PDF."""

    replacement_count: int


class PdfFileResponse(BaseModel):
    job_id: str
    download_name: str
    download_url: str


class RedactResponse(PdfFileResponse):
    redacted_count: int
    metadata_scrubbed: bool
    verified_unrecoverable: bool


class MarkdownResponse(PdfFileResponse):
    page_count: int
    word_count: int
    estimated_tokens: int
    markdown: str
