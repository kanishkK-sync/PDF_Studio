"""Tests for the compression engine and POST /api/compress."""

import json
import threading
import time
from collections.abc import Callable
from pathlib import Path

import pymupdf
import pytest
from fastapi.testclient import TestClient
from httpx import Response

from app.api.routes import compress as compress_route
from app.core.config import get_settings
from app.core.errors import (
    CORRUPT,
    ENCRYPTED,
    INVALID_LEVEL,
    INVALID_REQUEST,
    NOT_PDF,
    PROCESSING_FAILED,
    TOO_LARGE,
    AppError,
)
from app.services import compress as compress_module
from app.services.compress import CompressionResult, compress_pdf, parse_level

PdfFactory = Callable[..., Path]
PostCompress = Callable[..., Response]

LEVELS = ["light", "balanced", "strong"]
CONTRACT_FIELDS = {
    "job_id",
    "original_name",
    "original_size",
    "compressed_size",
    "saved_bytes",
    "saved_percent",
    "already_optimized",
    "level",
    "download_url",
}


def _out(tmp_path: Path) -> Path:
    folder = tmp_path / "out"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "result.pdf"


def _page_texts(path: Path) -> list[str]:
    document = pymupdf.open(str(path))
    try:
        return [" ".join(page.get_text().split()) for page in document]
    finally:
        document.close()


def _summary(path: Path) -> dict[str, object]:
    document = pymupdf.open(str(path))
    try:
        return {
            "pages": document.page_count,
            "sizes": [
                (round(page.rect.width, 2), round(page.rect.height, 2))
                for page in document
            ],
            "toc": document.get_toc(),
            "links": [len(page.get_links()) for page in document],
            "title": document.metadata.get("title"),
            "author": document.metadata.get("author"),
        }
    finally:
        document.close()


def _wait_until(predicate: Callable[[], bool], timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


# -- Engine --------------------------------------------------------------------


@pytest.mark.parametrize("level", LEVELS)
def test_each_level_produces_a_valid_pdf(
    image_pdf: Path, tmp_path: Path, level: str
) -> None:
    output = _out(tmp_path)
    original_size = image_pdf.stat().st_size

    result = compress_pdf(image_pdf, output, level)

    assert result.original_size == original_size
    assert result.compressed_size == output.stat().st_size
    assert result.compressed_size <= original_size
    assert result.page_count == 4
    assert _page_texts(output) == _page_texts(image_pdf)
    if level != "light":
        assert result.already_optimized is False
        assert result.compressed_size < original_size


def test_strong_is_not_larger_than_balanced(image_pdf: Path, tmp_path: Path) -> None:
    balanced = compress_pdf(image_pdf, _out(tmp_path / "b"), "balanced")
    strong = compress_pdf(image_pdf, _out(tmp_path / "s"), "strong")

    assert strong.compressed_size <= balanced.compressed_size


@pytest.mark.parametrize("level", LEVELS)
def test_text_only_pdf_never_grows(text_pdf: Path, tmp_path: Path, level: str) -> None:
    output = _out(tmp_path)

    result = compress_pdf(text_pdf, output, level)

    assert result.compressed_size <= result.original_size
    assert output.stat().st_size == result.compressed_size
    assert _page_texts(output) == _page_texts(text_pdf)


def test_original_is_returned_when_nothing_is_smaller(
    text_pdf: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bigger = tmp_path / "bigger.pdf"
    bigger.write_bytes(text_pdf.read_bytes() + b"\n%" + b"x" * 1024)
    monkeypatch.setattr(
        compress_module,
        "_collect_candidates",
        lambda input_path, work_dir, level: [
            compress_module._Candidate(bigger, frozenset())
        ],
    )
    output = _out(tmp_path)

    result = compress_pdf(text_pdf, output, "light")

    assert result.already_optimized is True
    assert result.compressed_size == result.original_size
    assert output.read_bytes() == text_pdf.read_bytes()


def test_original_is_returned_when_the_only_candidate_fails_validation(
    text_pdf: Path,
    tmp_path: Path,
    pdf_factory: PdfFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    one_page = pdf_factory(tmp_path / "one.pdf", pages=1)
    assert one_page.stat().st_size < text_pdf.stat().st_size
    monkeypatch.setattr(
        compress_module,
        "_collect_candidates",
        lambda input_path, work_dir, level: [
            compress_module._Candidate(one_page, frozenset())
        ],
    )
    output = _out(tmp_path)

    result = compress_pdf(text_pdf, output, "light")

    assert result.already_optimized is True
    assert output.read_bytes() == text_pdf.read_bytes()


def test_invalid_smaller_candidate_is_skipped_in_favour_of_a_valid_one(
    image_pdf: Path,
    tmp_path: Path,
    pdf_factory: PdfFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tiny = pdf_factory(tmp_path / "tiny.pdf", pages=1)
    real = compress_module._collect_candidates

    def with_bogus(input_path: Path, work_dir: Path, level: str) -> list:
        return [*real(input_path, work_dir, level), compress_module._Candidate(
            tiny, frozenset()
        )]

    monkeypatch.setattr(compress_module, "_collect_candidates", with_bogus)
    output = _out(tmp_path)

    result = compress_pdf(image_pdf, output, "balanced")

    assert result.already_optimized is False
    assert result.page_count == 4
    assert _page_texts(output) == _page_texts(image_pdf)


def test_encrypted_pdf_is_rejected(encrypted_pdf: Path, tmp_path: Path) -> None:
    output = _out(tmp_path)

    with pytest.raises(AppError) as info:
        compress_pdf(encrypted_pdf, output, "balanced")

    assert info.value.code == ENCRYPTED
    assert not output.exists()


def test_garbage_behind_a_pdf_header_is_corrupt(tmp_path: Path) -> None:
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"%PDF-1.7\n" + b"garbage " * 200)
    output = _out(tmp_path)

    with pytest.raises(AppError) as info:
        compress_pdf(broken, output, "balanced")

    assert info.value.code == CORRUPT


def test_parse_level_accepts_only_the_three_levels() -> None:
    for level in LEVELS:
        assert parse_level(level) == level
    for bad in ("Balanced", "", "extreme", None, 1):
        with pytest.raises(AppError) as info:
            parse_level(bad)
        assert info.value.code == INVALID_LEVEL


def test_metadata_bookmarks_links_and_page_sizes_survive(
    image_pdf: Path, tmp_path: Path
) -> None:
    output = _out(tmp_path)

    compress_pdf(image_pdf, output, "balanced")

    before = _summary(image_pdf)
    after = _summary(output)
    assert after == before
    assert after["title"] == "Test document"
    assert after["author"] == "Test Author"
    assert after["links"][0] >= 1  # type: ignore[index]


def test_work_folder_is_removed_after_success(
    text_pdf: Path, tmp_path: Path
) -> None:
    output = _out(tmp_path)

    compress_pdf(text_pdf, output, "balanced")

    assert [entry.name for entry in output.parent.iterdir()] == ["result.pdf"]


def test_unexpected_failure_becomes_processing_failed_and_cleans_up(
    text_pdf: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def explode(input_path: Path, work_dir: Path, level: str) -> list:
        raise RuntimeError("boom at /secret/path")

    monkeypatch.setattr(compress_module, "_collect_candidates", explode)
    output = _out(tmp_path)

    with pytest.raises(AppError) as info:
        compress_pdf(text_pdf, output, "balanced")

    assert info.value.code == PROCESSING_FAILED
    assert "secret" not in info.value.message
    assert list(output.parent.iterdir()) == []


def test_concurrency_limit_is_enforced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MAX_CONCURRENT_JOBS", "2")
    get_settings.cache_clear()
    compress_module.rebuild_concurrency_gate()

    lock = threading.Lock()
    release = threading.Event()
    state = {"active": 0, "peak": 0, "entered": 0}

    def fake(input_path: Path, output_path: Path, level: str) -> CompressionResult:
        with lock:
            state["active"] += 1
            state["entered"] += 1
            state["peak"] = max(state["peak"], state["active"])
        try:
            release.wait(timeout=10)
        finally:
            with lock:
                state["active"] -= 1
        return CompressionResult(1, 1, True, 1)

    monkeypatch.setattr(compress_module, "_compress_locked", fake)
    threads = [
        threading.Thread(
            target=compress_pdf,
            args=(tmp_path / "in.pdf", tmp_path / "out.pdf", "light"),
        )
        for _ in range(3)
    ]
    for thread in threads:
        thread.start()
    try:
        assert _wait_until(lambda: state["entered"] == 2)
        time.sleep(0.3)
        assert state["entered"] == 2  # the third worker is still waiting
        release.set()
        assert _wait_until(lambda: state["entered"] == 3)
    finally:
        release.set()
        for thread in threads:
            thread.join(timeout=10)

    assert state["peak"] == 2


# -- Route ---------------------------------------------------------------------


def test_success_returns_every_contract_field(
    post_compress: PostCompress,
    image_pdf: Path,
    storage_dir: Path,
) -> None:
    content = image_pdf.read_bytes()

    response = post_compress(content, level="balanced", filename="Quarterly report.pdf")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == CONTRACT_FIELDS
    assert body["original_name"] == "Quarterly report"
    assert body["original_size"] == len(content)
    assert body["level"] == "balanced"
    assert body["already_optimized"] is False
    assert body["saved_bytes"] == body["original_size"] - body["compressed_size"]
    assert body["saved_percent"] == round(
        body["saved_bytes"] / body["original_size"] * 100, 1
    )
    assert body["download_url"] == f"/api/jobs/{body['job_id']}/download"

    output_dir = storage_dir / "outputs" / body["job_id"]
    assert (output_dir / "result.pdf").stat().st_size == body["compressed_size"]
    meta = json.loads((output_dir / "meta.json").read_text(encoding="utf-8"))
    assert meta["original_name"] == "Quarterly report"
    assert not (storage_dir / "uploads" / body["job_id"]).exists()


def test_bad_level_gives_invalid_level_and_creates_no_job(
    post_compress: PostCompress,
    text_pdf: Path,
    job_entries: Callable[[], list[str]],
) -> None:
    response = post_compress(text_pdf.read_bytes(), level="extreme")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == INVALID_LEVEL
    assert job_entries() == []


def test_missing_level_gives_invalid_level(
    post_compress: PostCompress, text_pdf: Path
) -> None:
    response = post_compress(text_pdf.read_bytes(), level=None)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == INVALID_LEVEL


@pytest.mark.parametrize(
    ("kind", "status", "code"),
    [
        ("not_pdf", 400, NOT_PDF),
        ("encrypted", 400, ENCRYPTED),
        ("corrupt", 400, CORRUPT),
    ],
)
def test_failures_use_contract_errors_and_leave_no_files(
    kind: str,
    status: int,
    code: str,
    post_compress: PostCompress,
    encrypted_pdf: Path,
    job_entries: Callable[[], list[str]],
) -> None:
    contents = {
        "not_pdf": b"this is plain text, not a pdf. " * 20,
        "encrypted": encrypted_pdf.read_bytes(),
        "corrupt": b"%PDF-1.7\n" + b"garbage " * 200,
    }

    response = post_compress(contents[kind])

    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    assert job_entries() == []


def test_upload_just_over_the_limit_is_too_large(
    post_compress: PostCompress,
    monkeypatch: pytest.MonkeyPatch,
    job_entries: Callable[[], list[str]],
) -> None:
    monkeypatch.setenv("MAX_UPLOAD_MB", "1")
    get_settings.cache_clear()
    content = b"%PDF-" + b"0" * (1024 * 1024 - 4)  # exactly 1 MiB + 1 byte
    assert len(content) == 1024 * 1024 + 1

    response = post_compress(content)

    assert response.status_code == 413
    error = response.json()["error"]
    assert error["code"] == TOO_LARGE
    assert "1 MB" in error["message"]
    assert job_entries() == []


def test_missing_file_field_is_invalid_request(client: TestClient) -> None:
    response = client.post("/api/compress", data={"level": "balanced"})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == INVALID_REQUEST


def test_empty_file_is_not_a_pdf(
    post_compress: PostCompress, job_entries: Callable[[], list[str]]
) -> None:
    response = post_compress(b"")

    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == NOT_PDF
    assert "empty" in error["message"]
    assert job_entries() == []


def test_already_optimized_result_is_the_original_bytes(
    post_compress: PostCompress,
    client: TestClient,
    text_pdf: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        compress_module, "_collect_candidates", lambda input_path, work_dir, level: []
    )
    content = text_pdf.read_bytes()

    response = post_compress(content, level="strong")

    assert response.status_code == 200
    body = response.json()
    assert body["already_optimized"] is True
    assert body["saved_bytes"] == 0
    assert body["saved_percent"] == 0.0
    assert body["compressed_size"] == body["original_size"] == len(content)
    assert client.get(body["download_url"]).content == content


def test_engine_failure_returns_processing_failed_without_details(
    post_compress: PostCompress,
    text_pdf: Path,
    job_entries: Callable[[], list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def explode(input_path: Path, output_path: Path, level: str) -> CompressionResult:
        raise RuntimeError("boom at /secret/path")

    monkeypatch.setattr(compress_module, "_compress_locked", explode)

    response = post_compress(text_pdf.read_bytes())

    assert response.status_code == 500
    assert response.json()["error"]["code"] == PROCESSING_FAILED
    assert "secret" not in response.text
    assert job_entries() == []


def test_unexpected_error_returns_internal_error_and_cleans_up(
    post_compress: PostCompress,
    text_pdf: Path,
    job_entries: Callable[[], list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def explode(*args: object, **kwargs: object) -> None:
        raise RuntimeError("boom at /secret/path")

    monkeypatch.setattr(compress_route, "compress_pdf", explode)

    response = post_compress(text_pdf.read_bytes())

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert "secret" not in response.text
    assert job_entries() == []