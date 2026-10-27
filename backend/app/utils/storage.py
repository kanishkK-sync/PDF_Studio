"""Job storage: ids, per-job folders, metadata, sweeping and purging.

Layout under the storage directory:

    uploads/<job_id>/   the uploaded original (deleted as soon as processing ends)
    outputs/<job_id>/   the result file and meta.json (deleted after download)

Every path handed out is resolved and checked to stay inside the storage
directory. Removals never follow symlinks.
"""

import json
import os
import re
import shutil
import time
import uuid
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.core.errors import JOB_NOT_FOUND, AppError

UPLOADS = "uploads"
OUTPUTS = "outputs"
META_NAME = "meta.json"

_KEEP_NAME = ".gitkeep"
_JOB_ID_PATTERN = re.compile(r"[0-9a-f]{32}")


# ── Job ids ──────────────────────────────────────────────────────────────────


def new_job_id() -> str:
    """A random job id: a UUID in hex form (32 lowercase hex characters)."""
    return uuid.uuid4().hex


def is_valid_job_id(job_id: object) -> bool:
    """True only for exactly 32 lowercase hex characters, nothing else."""
    return isinstance(job_id, str) and _JOB_ID_PATTERN.fullmatch(job_id) is not None


# ── Paths ────────────────────────────────────────────────────────────────────


def storage_root() -> Path:
    """The resolved storage directory."""
    return get_settings().storage_dir.resolve()


def _kind_root(kind: str) -> Path:
    root = storage_root() / kind
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


def _resolve_job_dir(kind: str, job_id: str) -> Path | None:
    """The job's folder, or None if the id is invalid or the path leaves storage."""
    if not is_valid_job_id(job_id):
        return None
    base = _kind_root(kind)
    path = (base / job_id).resolve()
    return path if path.is_relative_to(base) else None


def _job_dir(kind: str, job_id: str, create: bool) -> Path:
    path = _resolve_job_dir(kind, job_id)
    if path is None:
        raise AppError(JOB_NOT_FOUND)
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def get_upload_dir(job_id: str, create: bool = False) -> Path:
    """The folder for a job's uploaded original. Raises job_not_found for a bad id."""
    return _job_dir(UPLOADS, job_id, create)


def get_output_dir(job_id: str, create: bool = False) -> Path:
    """The folder for a job's result and metadata. Raises job_not_found for a bad id."""
    return _job_dir(OUTPUTS, job_id, create)


# ── Removal ──────────────────────────────────────────────────────────────────


def _remove_entry(path: Path) -> None:
    """Best-effort removal of a file, a symlink (never its target) or a folder."""
    try:
        if path.is_symlink() or path.is_file():
            path.unlink(missing_ok=True)
        else:
            shutil.rmtree(path, ignore_errors=True)
    except OSError:
        pass  # e.g. a file still open on Windows; the sweeper will try again


def delete_job(job_id: str) -> bool:
    """Delete a job's upload and output folders.

    Safe to repeat and safe to call with anything: invalid ids and paths that
    would leave storage are ignored. Returns True if something was removed.
    """
    removed = False
    for kind in (UPLOADS, OUTPUTS):
        path = _resolve_job_dir(kind, job_id)
        if path is not None and path.exists():
            _remove_entry(path)
            removed = True
    return removed


def _entries_by_name() -> dict[str, list[Path]]:
    """Everything in uploads/ and outputs/ (except .gitkeep), grouped by name."""
    grouped: dict[str, list[Path]] = {}
    for kind in (UPLOADS, OUTPUTS):
        for entry in _kind_root(kind).iterdir():
            if entry.name != _KEEP_NAME:
                grouped.setdefault(entry.name, []).append(entry)
    return grouped


def sweep_expired() -> int:
    """Delete jobs older than the TTL, judged by modification time.

    A job is as new as its newest folder. Stray entries are swept like jobs.
    Returns how many jobs (distinct names) were removed.
    """
    cutoff = time.time() - get_settings().job_ttl_minutes * 60
    removed = 0
    for entries in _entries_by_name().values():
        try:
            newest = max(entry.lstat().st_mtime for entry in entries)
        except FileNotFoundError:
            continue  # deleted by a request while we were looking
        if newest < cutoff:
            for entry in entries:
                _remove_entry(entry)
            removed += 1
    return removed


def purge_all() -> int:
    """Empty both storage folders, keeping the folders and .gitkeep.

    Returns how many jobs (distinct names) were removed.
    """
    grouped = _entries_by_name()
    for entries in grouped.values():
        for entry in entries:
            _remove_entry(entry)
    return len(grouped)


# ── Metadata ─────────────────────────────────────────────────────────────────


def _meta_file(job_id: str, create: bool, suffix: str = "") -> Path:
    directory = get_output_dir(job_id, create=create)
    path = (directory / (META_NAME + suffix)).resolve()
    if not path.is_relative_to(directory):
        raise AppError(JOB_NOT_FOUND)
    return path


def write_meta(job_id: str, data: dict[str, Any]) -> None:
    """Write the job's small JSON metadata file into its output folder."""
    target = _meta_file(job_id, create=True)
    temporary = _meta_file(job_id, create=True, suffix=".tmp")
    temporary.write_text(json.dumps(data), encoding="utf-8")
    os.replace(temporary, target)


def read_meta(job_id: str) -> dict[str, Any] | None:
    """The job's metadata, or None if it is missing or unreadable."""
    path = _meta_file(job_id, create=False)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None