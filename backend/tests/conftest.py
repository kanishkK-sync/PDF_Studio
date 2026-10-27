"""Shared test fixtures."""

from collections.abc import Iterator
from pathlib import Path

import pytest

from app.core.config import get_settings


@pytest.fixture
def storage_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Point the storage directory at a fresh temporary folder.

    The folder is `<tmp>/storage`, so tests can use its parent as a place
    outside storage. Sets STORAGE_DIR through the environment and clears the
    settings cache before and after; monkeypatch restores the environment.
    """
    root = tmp_path / "storage"
    root.mkdir()
    monkeypatch.setenv("STORAGE_DIR", str(root))
    get_settings.cache_clear()
    yield root
    get_settings.cache_clear()