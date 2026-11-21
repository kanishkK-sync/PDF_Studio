"""Application settings, loaded from environment variables and backend/.env."""

from functools import lru_cache
from pathlib import Path

from pydantic import PositiveInt
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/core/config.py -> backend/app/storage, wherever the server is started.
_DEFAULT_STORAGE_DIR = Path(__file__).resolve().parent.parent / "storage"


class Settings(BaseSettings):
    """Runtime configuration.

    Field names match the variables in .env.example (case-insensitive).
    Every field has a default, so the app also starts without a .env file.
    """

    app_name: str = "pdf-studio"
    app_version: str = "0.1.0"
    frontend_origin: str = "http://localhost:3000"
    rate_limit_per_minute: PositiveInt = 30

    max_upload_mb: PositiveInt = 100
    job_ttl_minutes: PositiveInt = 30
    max_concurrent_jobs: PositiveInt = 1
    storage_dir: Path = _DEFAULT_STORAGE_DIR

    # Phase 2 conversion limits.
    max_pdf_pages: PositiveInt = 300
    max_images: PositiveInt = 50
    max_render_pixels: PositiveInt = 30_000_000

    # Most PDFs merged in one job.
    max_merge_files: PositiveInt = 20

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance."""
    return Settings()
