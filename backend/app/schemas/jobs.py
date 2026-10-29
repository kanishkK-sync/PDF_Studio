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