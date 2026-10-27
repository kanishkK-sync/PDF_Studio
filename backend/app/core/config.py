"""Application settings, loaded from environment variables and backend/.env."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration.

    Field names match the variables in .env.example (case-insensitive).
    Every field has a default, so the app also starts without a .env file.
    """

    app_name: str = "pdf-studio"
    app_version: str = "0.1.0"
    frontend_origin: str = "http://localhost:3000"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance."""
    return Settings()