"""Tests for job storage and the upload helpers."""

import asyncio
import io
import os
import time
import uuid
from pathlib import Path

import pytest
from fastapi import UploadFile

from app.core.config import get_settings
from app.core.errors import AppError
from app.utils import storage, uploads

MEGABYTE = 1024 * 1024
DAY = 24 * 60 * 60


# ── Helpers ──────────────────────────────────────────────────────────────────


def make_job(*, upload: bool = True, output: bool = True) -> str:
    """Create a job with a small file in each requested folder."""
    job_id = storage.new_job_id()
    if upload:
        (storage.get_upload_dir(job_id, create=True) / "original.pdf").write_bytes(b"%PDF-1.7")
    if output:
        (storage.get_output_dir(job_id, create=True) / "result.pdf").write_bytes(b"%PDF-1.7")
    return job_id


def age(path: Path, seconds: float) -> None:
    """Backdate a path's modification time."""
    stamp = time.time() - seconds
    os.utime(path, (stamp, stamp))


def make_upload(data: bytes) -> UploadFile:
    return UploadFile(file=io.BytesIO(data), filename="input.pdf")


def run_save(upload: UploadFile, destination: Path, max_bytes: int) -> int:
    return asyncio.run(uploads.save_upload(upload, destination, max_bytes))


# ── Job ids ──────────────────────────────────────────────────────────────────


def test_new_job_id_is_32_lowercase_hex_and_unique() -> None:
    ids = {storage.new_job_id() for _ in range(50)}

    assert len(ids) == 50
    assert all(storage.is_valid_job_id(job_id) for job_id in ids)
    assert all(len(job_id) == 32 and job_id == job_id.lower() for job_id in ids)


@pytest.mark.parametrize(
    "job_id",
    [uuid.uuid4().hex, "0" * 32, "a" * 32, "0123456789abcdef" * 2],
)
def test_valid_job_ids_are_accepted(job_id: str) -> None:
    assert storage.is_valid_job_id(job_id) is True


@pytest.mark.parametrize(
    "job_id",
    [
        "",
        "a" * 31,
        "a" * 33,
        "A" * 32,
        "g" * 32,
        str(uuid.uuid4()),
        "../x",
        "../" + "a" * 29,
        "/etc/passwd",
        "..\\x",
        "C:\\Windows\\win.ini",
        "a" * 16 + "/" + "a" * 15,
        "a" * 32 + "\n",
        " " + "a" * 31,
        "\u0660" * 32,
    ],
)
def test_invalid_job_ids_are_rejected(job_id: str) -> None:
    assert storage.is_valid_job_id(job_id) is False


@pytest.mark.parametrize("job_id", ["../x", "../../" + "a" * 32, "/etc/passwd", "..", "a" * 31])
def test_folder_getters_reject_bad_ids_with_job_not_found(storage_dir: Path, job_id: str) -> None:
    for getter in (storage.get_upload_dir, storage.get_output_dir):
        with pytest.raises(AppError) as caught:
            getter(job_id)
        assert caught.value.code == "job_not_found"
        assert caught.value.status_code == 404


# ── Job folders ──────────────────────────────────────────────────────────────


def test_job_folders_live_under_storage_and_are_created_on_demand(storage_dir: Path) -> None:
    job_id = storage.new_job_id()
    upload_dir = storage.get_upload_dir(job_id)
    output_dir = storage.get_output_dir(job_id)

    assert upload_dir == storage_dir.resolve() / "uploads" / job_id
    assert output_dir == storage_dir.resolve() / "outputs" / job_id
    assert not upload_dir.exists()
    assert not output_dir.exists()

    assert storage.get_upload_dir(job_id, create=True).is_dir()
    assert storage.get_output_dir(job_id, create=True).is_dir()


# ── Deleting jobs ────────────────────────────────────────────────────────────


def test_delete_job_removes_both_folders_and_is_safe_to_repeat(storage_dir: Path) -> None:
    job_id = make_job()

    assert storage.delete_job(job_id) is True
    assert not (storage_dir / "uploads" / job_id).exists()
    assert not (storage_dir / "outputs" / job_id).exists()

    assert storage.delete_job(job_id) is False
    assert storage.delete_job(storage.new_job_id()) is False


def test_delete_job_ignores_bad_ids_and_leaves_outside_files_alone(storage_dir: Path) -> None:
    outside = storage_dir.parent / "outside"
    outside.mkdir()
    (outside / "precious.txt").write_text("keep me")

    for job_id in ("../outside", "../../outside", str(outside), ""):
        assert storage.delete_job(job_id) is False

    assert (outside / "precious.txt").read_text() == "keep me"


def test_symlinked_job_folder_cannot_reach_outside_storage(storage_dir: Path) -> None:
    outside = storage_dir.parent / "outside"
    outside.mkdir()
    (outside / "precious.txt").write_text("keep me")

    job_id = storage.new_job_id()
    storage.get_upload_dir(job_id)  # makes sure uploads/ exists
    link = storage_dir / "uploads" / job_id
    try:
        os.symlink(outside, link, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("this system does not allow creating symlinks")

    with pytest.raises(AppError) as caught:
        storage.get_upload_dir(job_id)
    assert caught.value.code == "job_not_found"

    assert storage.delete_job(job_id) is False
    assert (outside / "precious.txt").read_text() == "keep me"

    assert storage.purge_all() == 1
    assert not link.is_symlink()
    assert (outside / "precious.txt").read_text() == "keep me"


# ── Sweeping ─────────────────────────────────────────────────────────────────


def test_sweep_removes_only_backdated_jobs(storage_dir: Path) -> None:
    old_both = make_job()
    old_output_only = make_job(upload=False)
    fresh = make_job()

    age(storage.get_upload_dir(old_both), DAY)
    age(storage.get_output_dir(old_both), DAY)
    age(storage.get_output_dir(old_output_only), DAY)

    assert storage.sweep_expired() == 2

    for job_id in (old_both, old_output_only):
        assert not (storage_dir / "uploads" / job_id).exists()
        assert not (storage_dir / "outputs" / job_id).exists()
    assert (storage_dir / "uploads" / fresh).is_dir()
    assert (storage_dir / "outputs" / fresh).is_dir()


def test_sweep_keeps_a_job_while_any_of_its_folders_is_recent(storage_dir: Path) -> None:
    job_id = make_job()
    age(storage.get_output_dir(job_id), DAY)

    assert storage.sweep_expired() == 0
    assert (storage_dir / "uploads" / job_id).is_dir()
    assert (storage_dir / "outputs" / job_id).is_dir()


def test_sweep_follows_the_ttl_setting(storage_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JOB_TTL_MINUTES", "1")
    get_settings.cache_clear()

    expired = make_job()
    recent = make_job()
    age(storage.get_output_dir(expired), 120)
    age(storage.get_upload_dir(expired), 120)
    age(storage.get_output_dir(recent), 30)
    age(storage.get_upload_dir(recent), 30)

    assert storage.sweep_expired() == 1
    assert not (storage_dir / "outputs" / expired).exists()
    assert (storage_dir / "outputs" / recent).is_dir()


def test_sweep_removes_old_stray_entries_but_never_gitkeep(storage_dir: Path) -> None:
    uploads_root = storage_dir / "uploads"
    uploads_root.mkdir()
    keep = uploads_root / ".gitkeep"
    stray = uploads_root / "stray.txt"
    keep.write_text("")
    stray.write_text("left over")
    age(keep, DAY)
    age(stray, DAY)

    assert storage.sweep_expired() == 1
    assert keep.exists()
    assert not stray.exists()


# ── Purging ──────────────────────────────────────────────────────────────────


def test_purge_all_empties_storage_but_keeps_folders_and_gitkeep(storage_dir: Path) -> None:
    for kind in ("uploads", "outputs"):
        (storage_dir / kind).mkdir()
        (storage_dir / kind / ".gitkeep").write_text("")
    make_job()
    make_job(output=False)
    (storage_dir / "uploads" / "stray.txt").write_text("left over")

    assert storage.purge_all() == 3

    for kind in ("uploads", "outputs"):
        remaining = [entry.name for entry in (storage_dir / kind).iterdir()]
        assert remaining == [".gitkeep"]


def test_purge_all_on_empty_storage_removes_nothing(storage_dir: Path) -> None:
    assert storage.purge_all() == 0
    assert (storage_dir / "uploads").is_dir()
    assert (storage_dir / "outputs").is_dir()


# ── Metadata ─────────────────────────────────────────────────────────────────


def test_meta_round_trips_through_the_output_folder(storage_dir: Path) -> None:
    job_id = storage.new_job_id()
    data = {"original_name": "Report", "level": "light"}

    storage.write_meta(job_id, data)

    assert storage.read_meta(job_id) == data
    assert [p.name for p in storage.get_output_dir(job_id).iterdir()] == ["meta.json"]


def test_read_meta_returns_none_when_missing_or_unreadable(storage_dir: Path) -> None:
    job_id = make_job()
    meta_path = storage.get_output_dir(job_id) / "meta.json"

    assert storage.read_meta(job_id) is None

    meta_path.write_text("not json at all")
    assert storage.read_meta(job_id) is None

    meta_path.write_text("[1, 2, 3]")
    assert storage.read_meta(job_id) is None


def test_meta_functions_reject_bad_ids(storage_dir: Path) -> None:
    with pytest.raises(AppError) as read_error:
        storage.read_meta("../x")
    with pytest.raises(AppError) as write_error:
        storage.write_meta("../x", {})

    assert read_error.value.code == "job_not_found"
    assert write_error.value.code == "job_not_found"


# ── Saving uploads ───────────────────────────────────────────────────────────


def test_save_upload_writes_the_whole_file_across_several_chunks(tmp_path: Path) -> None:
    data = bytes(range(256)) * (3 * MEGABYTE // 256)  # exactly 3 MB: three chunks
    destination = tmp_path / "saved.pdf"

    written = run_save(make_upload(data), destination, 10 * MEGABYTE)

    assert written == len(data)
    assert destination.read_bytes() == data


def test_save_upload_accepts_a_file_exactly_at_the_cap(tmp_path: Path) -> None:
    destination = tmp_path / "saved.pdf"

    assert run_save(make_upload(b"x" * 10), destination, 10) == 10
    assert destination.read_bytes() == b"x" * 10


def test_save_upload_rejects_oversize_files_and_removes_the_partial_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(uploads, "CHUNK_SIZE", 4)
    destination = tmp_path / "saved.pdf"

    class SpyUpload(UploadFile):
        def __init__(self) -> None:
            super().__init__(file=io.BytesIO(b"x" * 20), filename="big.pdf")
            self.file_existed_at_read: list[bool] = []

        async def read(self, size: int = -1) -> bytes:
            self.file_existed_at_read.append(destination.exists())
            return await super().read(size)

    upload = SpyUpload()
    with pytest.raises(AppError) as caught:
        run_save(upload, destination, 10)

    assert caught.value.code == "too_large"
    assert caught.value.status_code == 413
    assert upload.file_existed_at_read[-1] is True  # the partial file did exist...
    assert not destination.exists()  # ...and is gone now


def test_too_large_message_names_the_limit_for_whole_megabytes(tmp_path: Path) -> None:
    destination = tmp_path / "saved.pdf"

    with pytest.raises(AppError) as caught:
        run_save(make_upload(b"x" * (2 * MEGABYTE + 1)), destination, 2 * MEGABYTE)

    assert "2 MB" in caught.value.message
    assert not destination.exists()


def test_save_upload_removes_the_partial_file_when_reading_fails(tmp_path: Path) -> None:
    destination = tmp_path / "saved.pdf"

    class BrokenUpload(UploadFile):
        def __init__(self) -> None:
            super().__init__(file=io.BytesIO(b"x" * 10), filename="broken.pdf")
            self.calls = 0

        async def read(self, size: int = -1) -> bytes:
            self.calls += 1
            if self.calls == 2:
                raise RuntimeError("connection dropped")
            return await super().read(4)

    with pytest.raises(RuntimeError):
        run_save(BrokenUpload(), destination, 100)

    assert not destination.exists()


def test_save_upload_rejects_an_empty_file(tmp_path: Path) -> None:
    destination = tmp_path / "saved.pdf"

    with pytest.raises(AppError) as caught:
        run_save(make_upload(b""), destination, 10 * MEGABYTE)

    assert caught.value.code == "not_pdf"
    assert caught.value.status_code == 400
    assert "empty" in caught.value.message.lower()
    assert not destination.exists()


# ── PDF signature ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        (b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n", True),
        (b"\xef\xbb\xbf%PDF-1.4\n", True),
        (b"junk" * 100 + b"%PDF-1.5\n", True),
        (b"a" * 1024 + b"%PDF-1.5\n", False),
        (b"%PDF", False),
        (b"hello world", False),
        (b"PK\x03\x04 a zip file", False),
        (b"", False),
    ],
)
def test_looks_like_pdf_checks_the_first_1024_bytes(
    tmp_path: Path, content: bytes, expected: bool
) -> None:
    path = tmp_path / "file.bin"
    path.write_bytes(content)

    assert uploads.looks_like_pdf(path) is expected


def test_looks_like_pdf_ignores_the_file_name(tmp_path: Path) -> None:
    pdf_named_txt = tmp_path / "notes.txt"
    pdf_named_txt.write_bytes(b"%PDF-1.7\n")
    text_named_pdf = tmp_path / "report.pdf"
    text_named_pdf.write_bytes(b"just some text")

    assert uploads.looks_like_pdf(pdf_named_txt) is True
    assert uploads.looks_like_pdf(text_named_pdf) is False


# ── Display names ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("Report.pdf", "Report"),
        ("Quarterly Report.PDF", "Quarterly Report"),
        ("report.final.v2.pdf", "report.final.v2"),
        ("no-extension", "no-extension"),
        ("C:\\Users\\me\\My Report.pdf", "My Report"),
        ("/tmp/uploads/report.pdf", "report"),
        ("../../secret.pdf", "secret"),
        ('weird<>:"|?*name.pdf', "weirdname"),
        ("bad\x00na\nme\t.pdf", "badname"),
        ("invoice\u202egpj.pdf", "invoicegpj"),
        ("  spaced   out  .pdf", "spaced out"),
        ("name...pdf", "name"),
        ("r\u00e9sum\u00e9.pdf", "r\u00e9sum\u00e9"),
        ("a" * 300 + ".pdf", "a" * 100),
        ("a" * 99 + " b.pdf", "a" * 99),
        ("???.pdf", "document"),
        ("..", "document"),
        ("   ", "document"),
        ("", "document"),
        (None, "document"),
    ],
)
def test_safe_display_name(filename: str | None, expected: str) -> None:
    assert uploads.safe_display_name(filename) == expected