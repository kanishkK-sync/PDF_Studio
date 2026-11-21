"""Tests for the PDF to Word engine and POST /api/pdf-to-word."""

import io
import json
import re
import threading
import time
import zipfile
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from httpx import Response

from app.api.routes import pdf_to_word as pdf_to_word_route
from app.core.config import get_settings
from app.core.errors import (
    CORRUPT,
    ENCRYPTED,
    INVALID_REQUEST,
    JOB_NOT_FOUND,
    NOT_PDF,
    PROCESSING_FAILED,
    TOO_LARGE,
    TOO_MANY_PAGES,
    AppError,
)
from app.services import pdf_to_word as engine
from app.services.pdf_to_word import PdfToWordResult, convert_pdf_to_word

PdfFactory = Callable[..., Path]
PostPdfToWord = Callable[..., Response]

DOCX_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)
CONTRACT_FIELDS = {
    "job_id",
    "original_name",
    "page_count",
    "original_size",
    "result_size",
    "download_name",
    "download_url",
}


@pytest.fixture(autouse=True)
def _reset_pdf_to_word_gate() -> Iterator[None]:
    """Rebuild this engine's gate after every test in this module."""
    yield
    get_settings.cache_clear()
    engine.rebuild_concurrency_gate()


def _out(tmp_path: Path) -> Path:
    folder = tmp_path / "out"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _document_text(path: Path) -> str:
    """All text in the Word file, with whitespace collapsed."""
    with zipfile.ZipFile(path) as archive:
        xml = archive.read("word/document.xml").decode("utf-8")
    pieces = re.findall(r"<w:t(?:\s[^>]*)?>([^<]*)</w:t>", xml)
    return re.sub(r"\s+", " ", "".join(pieces))


def _wait_until(predicate: Callable[[], bool], timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


# -- Engine --------------------------------------------------------------------


def test_text_pdf_becomes_a_docx_with_its_text(
    pdf_factory: PdfFactory, tmp_path: Path
) -> None:
    source = pdf_factory(tmp_path / "three.pdf", pages=3)
    out = _out(tmp_path)

    result = convert_pdf_to_word(source, out)

    assert result.result_name == "result.docx"
    assert result.page_count == 3
    assert result.result_size == (out / "result.docx").stat().st_size
    assert [entry.name for entry in out.iterdir()] == ["result.docx"]
    assert "lazy dog" in _document_text(out / "result.docx")


def test_images_are_carried_into_the_docx(image_pdf: Path, tmp_path: Path) -> None:
    out = _out(tmp_path)

    convert_pdf_to_word(image_pdf, out)

    with zipfile.ZipFile(out / "result.docx") as archive:
        media = [name for name in archive.namelist() if name.startswith("word/media/")]
    assert media


def test_encrypted_pdf_is_rejected(encrypted_pdf: Path, tmp_path: Path) -> None:
    out = _out(tmp_path)

    with pytest.raises(AppError) as info:
        convert_pdf_to_word(encrypted_pdf, out)

    assert info.value.code == ENCRYPTED
    assert list(out.iterdir()) == []


def test_garbage_behind_a_pdf_header_is_corrupt(tmp_path: Path) -> None:
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"%PDF-1.7\n" + b"garbage " * 200)
    out = _out(tmp_path)

    with pytest.raises(AppError) as info:
        convert_pdf_to_word(broken, out)

    assert info.value.code == CORRUPT
    assert list(out.iterdir()) == []


def test_too_many_pages_is_rejected_before_converting(
    pdf_factory: PdfFactory, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MAX_PDF_PAGES", "2")
    get_settings.cache_clear()

    def forbidden(source: Path, destination: Path) -> None:
        raise AssertionError("the converter must not run")

    monkeypatch.setattr(engine, "_run_pdf2docx", forbidden)
    source = pdf_factory(tmp_path / "three.pdf", pages=3)
    out = _out(tmp_path)

    with pytest.raises(AppError) as info:
        convert_pdf_to_word(source, out)

    assert info.value.code == TOO_MANY_PAGES
    assert "3" in info.value.message
    assert "2" in info.value.message
    assert list(out.iterdir()) == []


def test_converter_failure_is_processing_failed_without_details(
    pdf_factory: PdfFactory, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def explode(source: Path, destination: Path) -> None:
        raise RuntimeError("boom at /secret/path")

    monkeypatch.setattr(engine, "_run_pdf2docx", explode)
    source = pdf_factory(tmp_path / "one.pdf", pages=1)
    out = _out(tmp_path)

    with pytest.raises(AppError) as info:
        convert_pdf_to_word(source, out)

    assert info.value.code == PROCESSING_FAILED
    assert "secret" not in info.value.message
    assert list(out.iterdir()) == []


def test_output_that_is_not_a_docx_is_processing_failed(
    pdf_factory: PdfFactory, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def write_garbage(source: Path, destination: Path) -> None:
        destination.write_bytes(b"this is not a zip file")

    monkeypatch.setattr(engine, "_run_pdf2docx", write_garbage)
    source = pdf_factory(tmp_path / "one.pdf", pages=1)
    out = _out(tmp_path)

    with pytest.raises(AppError) as info:
        convert_pdf_to_word(source, out)

    assert info.value.code == PROCESSING_FAILED
    assert list(out.iterdir()) == []


def test_concurrency_limit_is_enforced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MAX_CONCURRENT_JOBS", "2")
    get_settings.cache_clear()
    engine.rebuild_concurrency_gate()

    lock = threading.Lock()
    release = threading.Event()
    state = {"active": 0, "peak": 0, "entered": 0}

    def fake(input_path: Path, output_dir: Path) -> PdfToWordResult:
        with lock:
            state["active"] += 1
            state["entered"] += 1
            state["peak"] = max(state["peak"], state["active"])
        try:
            release.wait(timeout=10)
        finally:
            with lock:
                state["active"] -= 1
        return PdfToWordResult(1, 1, "result.docx")

    monkeypatch.setattr(engine, "_convert_locked", fake)
    threads = [
        threading.Thread(
            target=convert_pdf_to_word,
            args=(tmp_path / "in.pdf", tmp_path / "out"),
        )
        for _ in range(3)
    ]
    for thread in threads:
        thread.start()
    try:
        assert _wait_until(lambda: state["entered"] == 1)
        time.sleep(0.3)
        assert state["entered"] == 1  # all other workers are still waiting
        release.set()
        assert _wait_until(lambda: state["entered"] == 3)
    finally:
        release.set()
        for thread in threads:
            thread.join(timeout=10)

    assert state["peak"] == 1


# -- Route ---------------------------------------------------------------------


@pytest.fixture
def post_pdf_to_word(client: TestClient) -> PostPdfToWord:
    """post_pdf_to_word(content, filename="report.pdf")."""

    def _post(
        content: bytes,
        *,
        filename: str = "report.pdf",
        content_type: str = "application/pdf",
    ) -> Response:
        return client.post(
            "/api/pdf-to-word",
            files={"file": (filename, content, content_type)},
        )

    return _post


def test_success_returns_every_contract_field(
    post_pdf_to_word: PostPdfToWord,
    pdf_factory: PdfFactory,
    tmp_path: Path,
    storage_dir: Path,
) -> None:
    source = pdf_factory(tmp_path / "three.pdf", pages=3)

    response = post_pdf_to_word(source.read_bytes(), filename="Quarterly report.pdf")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == CONTRACT_FIELDS
    assert body["original_name"] == "Quarterly report"
    assert body["page_count"] == 3
    assert body["original_size"] == source.stat().st_size
    assert body["download_name"] == "Quarterly report.docx"
    assert body["download_url"] == f"/api/jobs/{body['job_id']}/download"

    output_dir = storage_dir / "outputs" / body["job_id"]
    assert (output_dir / "result.docx").stat().st_size == body["result_size"]
    meta = json.loads((output_dir / "meta.json").read_text(encoding="utf-8"))
    assert meta["result_name"] == "result.docx"
    assert meta["download_name"] == "Quarterly report.docx"
    assert not (storage_dir / "uploads" / body["job_id"]).exists()


@pytest.mark.parametrize(
    ("kind", "status", "code"),
    [
        ("not_pdf", 400, NOT_PDF),
        ("encrypted", 400, ENCRYPTED),
        ("corrupt", 400, CORRUPT),
        ("empty", 400, NOT_PDF),
    ],
)
def test_failures_use_contract_errors_and_leave_no_files(
    kind: str,
    status: int,
    code: str,
    post_pdf_to_word: PostPdfToWord,
    encrypted_pdf: Path,
    job_entries: Callable[[], list[str]],
) -> None:
    contents = {
        "not_pdf": b"this is plain text, not a pdf. " * 20,
        "encrypted": encrypted_pdf.read_bytes(),
        "corrupt": b"%PDF-1.7\n" + b"garbage " * 200,
        "empty": b"",
    }

    response = post_pdf_to_word(contents[kind])

    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    assert job_entries() == []


def test_too_many_pages_gives_413_and_leaves_no_files(
    post_pdf_to_word: PostPdfToWord,
    pdf_factory: PdfFactory,
    tmp_path: Path,
    job_entries: Callable[[], list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MAX_PDF_PAGES", "2")
    get_settings.cache_clear()
    content = pdf_factory(tmp_path / "three.pdf", pages=3).read_bytes()

    response = post_pdf_to_word(content)

    assert response.status_code == 413
    assert response.json()["error"]["code"] == TOO_MANY_PAGES
    assert job_entries() == []


def test_upload_just_over_the_limit_is_too_large(
    post_pdf_to_word: PostPdfToWord,
    job_entries: Callable[[], list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MAX_UPLOAD_MB", "1")
    get_settings.cache_clear()
    content = b"%PDF-" + b"0" * (1024 * 1024 - 4)  # exactly 1 MiB + 1 byte
    assert len(content) == 1024 * 1024 + 1

    response = post_pdf_to_word(content)

    assert response.status_code == 413
    error = response.json()["error"]
    assert error["code"] == TOO_LARGE
    assert "1 MB" in error["message"]
    assert job_entries() == []


def test_missing_file_field_is_invalid_request(client: TestClient) -> None:
    response = client.post("/api/pdf-to-word")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == INVALID_REQUEST


def test_engine_failure_returns_processing_failed_without_details(
    post_pdf_to_word: PostPdfToWord,
    text_pdf: Path,
    job_entries: Callable[[], list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def explode(source: Path, destination: Path) -> None:
        raise RuntimeError("boom at /secret/path")

    monkeypatch.setattr(engine, "_run_pdf2docx", explode)

    response = post_pdf_to_word(text_pdf.read_bytes())

    assert response.status_code == 500
    assert response.json()["error"]["code"] == PROCESSING_FAILED
    assert "secret" not in response.text
    assert job_entries() == []


def test_unexpected_error_returns_internal_error_and_cleans_up(
    post_pdf_to_word: PostPdfToWord,
    text_pdf: Path,
    job_entries: Callable[[], list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def explode(*args: object, **kwargs: object) -> None:
        raise RuntimeError("boom at /secret/path")

    monkeypatch.setattr(pdf_to_word_route, "convert_pdf_to_word", explode)

    response = post_pdf_to_word(text_pdf.read_bytes())

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert "secret" not in response.text
    assert job_entries() == []


def test_result_downloads_as_a_docx_once_and_deletes_the_job(
    client: TestClient,
    post_pdf_to_word: PostPdfToWord,
    pdf_factory: PdfFactory,
    tmp_path: Path,
    job_entries: Callable[[], list[str]],
) -> None:
    source = pdf_factory(tmp_path / "one.pdf", pages=1)
    job = post_pdf_to_word(source.read_bytes(), filename="report.pdf").json()

    response = client.get(str(job["download_url"]))

    assert response.status_code == 200
    assert response.headers["content-type"] == DOCX_TYPE
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["content-disposition"] == (
        'attachment; filename="report.docx"'
    )
    assert zipfile.is_zipfile(io.BytesIO(response.content))
    assert len(response.content) == job["result_size"]
    assert job_entries() == []

    second = client.get(str(job["download_url"]))
    assert second.status_code == 404
    assert second.json()["error"]["code"] == JOB_NOT_FOUND
