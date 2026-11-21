"""Tests for the PDF to JPG engine and POST /api/pdf-to-jpg."""

import io
import json
import threading
import time
import zipfile
from collections.abc import Callable
from pathlib import Path

import pytest
from app.api.routes import pdf_to_jpg as pdf_to_jpg_route
from app.core.config import get_settings
from app.core.errors import (
    CORRUPT,
    ENCRYPTED,
    INVALID_QUALITY,
    INVALID_REQUEST,
    NOT_PDF,
    PROCESSING_FAILED,
    TOO_LARGE,
    TOO_MANY_PAGES,
    AppError,
)
from app.services import pdf_to_jpg as engine
from app.services.pdf_to_jpg import PdfToJpgResult, convert_pdf_to_jpg, parse_quality
from fastapi.testclient import TestClient
from httpx import Response
from PIL import Image

PdfFactory = Callable[..., Path]
PostPdfToJpg = Callable[..., Response]

QUALITIES = ["low", "medium", "high"]
CONTRACT_FIELDS = {
    "job_id",
    "original_name",
    "page_count",
    "file_count",
    "result_size",
    "kind",
    "quality",
    "download_url",
}


def _out(tmp_path: Path) -> Path:
    folder = tmp_path / "out"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _jpeg_size(data: bytes) -> tuple[int, int]:
    """Assert the bytes are a decodable JPEG and return its (width, height)."""
    assert data.startswith(b"\xff\xd8\xff")
    with Image.open(io.BytesIO(data)) as image:
        image.verify()
    with Image.open(io.BytesIO(data)) as image:
        assert image.format == "JPEG"
        image.load()
        return image.size


def _wait_until(predicate: Callable[[], bool], timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


# -- Engine --------------------------------------------------------------------


@pytest.mark.parametrize("quality", QUALITIES)
def test_each_quality_produces_a_zip_of_valid_jpegs(
    pdf_factory: PdfFactory, tmp_path: Path, quality: str
) -> None:
    source = pdf_factory(tmp_path / "three.pdf", pages=3)
    out = _out(tmp_path)

    result = convert_pdf_to_jpg(source, out, quality)

    assert result.kind == "zip"
    assert result.result_name == "result.zip"
    assert result.page_count == 3
    assert result.file_count == 3
    assert result.result_size == (out / "result.zip").stat().st_size
    assert [entry.name for entry in out.iterdir()] == ["result.zip"]
    with zipfile.ZipFile(out / "result.zip") as archive:
        assert archive.namelist() == [
            "page-001.jpg",
            "page-002.jpg",
            "page-003.jpg",
        ]
        for info in archive.infolist():
            assert info.compress_type == zipfile.ZIP_STORED
            _jpeg_size(archive.read(info))


def test_a_single_page_gives_a_bare_jpg(
    pdf_factory: PdfFactory, tmp_path: Path
) -> None:
    source = pdf_factory(tmp_path / "one.pdf", pages=1)
    out = _out(tmp_path)

    result = convert_pdf_to_jpg(source, out, "medium")

    assert result.kind == "jpg"
    assert result.result_name == "result.jpg"
    assert result.page_count == 1
    assert result.file_count == 1
    assert [entry.name for entry in out.iterdir()] == ["result.jpg"]
    assert result.result_size == (out / "result.jpg").stat().st_size
    _jpeg_size((out / "result.jpg").read_bytes())


def test_higher_quality_means_more_pixels_and_bigger_files(
    pdf_factory: PdfFactory, tmp_path: Path
) -> None:
    source = pdf_factory(tmp_path / "one.pdf", pages=1)
    widths: dict[str, int] = {}
    sizes: dict[str, int] = {}

    for quality, dpi in (("low", 100), ("medium", 150), ("high", 220)):
        out = _out(tmp_path / quality)
        convert_pdf_to_jpg(source, out, quality)
        data = (out / "result.jpg").read_bytes()
        width, _height = _jpeg_size(data)
        assert abs(width - round(595 / 72 * dpi)) <= 2
        widths[quality] = width
        sizes[quality] = len(data)

    assert widths["low"] < widths["medium"] < widths["high"]
    assert sizes["low"] <= sizes["medium"] <= sizes["high"]


def test_encrypted_pdf_is_rejected(encrypted_pdf: Path, tmp_path: Path) -> None:
    out = _out(tmp_path)

    with pytest.raises(AppError) as info:
        convert_pdf_to_jpg(encrypted_pdf, out, "medium")

    assert info.value.code == ENCRYPTED
    assert list(out.iterdir()) == []


def test_garbage_behind_a_pdf_header_is_corrupt(tmp_path: Path) -> None:
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"%PDF-1.7\n" + b"garbage " * 200)
    out = _out(tmp_path)

    with pytest.raises(AppError) as info:
        convert_pdf_to_jpg(broken, out, "medium")

    assert info.value.code == CORRUPT
    assert list(out.iterdir()) == []


def test_too_many_pages_is_rejected_before_any_rendering(
    pdf_factory: PdfFactory, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MAX_PDF_PAGES", "2")
    get_settings.cache_clear()
    source = pdf_factory(tmp_path / "three.pdf", pages=3)
    out = _out(tmp_path)

    with pytest.raises(AppError) as info:
        convert_pdf_to_jpg(source, out, "medium")

    assert info.value.code == TOO_MANY_PAGES
    assert "3" in info.value.message
    assert "2" in info.value.message
    assert list(out.iterdir()) == []


def test_an_oversized_page_is_rendered_at_a_lower_dpi_instead_of_failing(
    pdf_factory: PdfFactory, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MAX_RENDER_PIXELS", "200000")
    get_settings.cache_clear()
    source = pdf_factory(tmp_path / "one.pdf", pages=1)
    out = _out(tmp_path)

    result = convert_pdf_to_jpg(source, out, "high")

    assert result.kind == "jpg"
    width, height = _jpeg_size((out / "result.jpg").read_bytes())
    assert 0 < width * height <= 200_000
    assert width < round(595 / 72 * 220)


def test_a_page_that_fails_to_render_fails_the_whole_job(
    pdf_factory: PdfFactory, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_encode = engine._encode_jpeg
    calls = {"count": 0}

    def flaky(pixmap: object, quality: int) -> bytes:
        calls["count"] += 1
        if calls["count"] == 2:
            raise RuntimeError("boom at /secret/path")
        return real_encode(pixmap, quality)

    monkeypatch.setattr(engine, "_encode_jpeg", flaky)
    source = pdf_factory(tmp_path / "three.pdf", pages=3)
    out = _out(tmp_path)

    with pytest.raises(AppError) as info:
        convert_pdf_to_jpg(source, out, "low")

    assert info.value.code == PROCESSING_FAILED
    assert "secret" not in info.value.message
    assert list(out.iterdir()) == []


def test_pillow_is_used_when_pixmap_jpeg_output_is_unavailable(
    pdf_factory: PdfFactory, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_pillow = engine._pillow_jpeg
    used: list[int] = []

    def unavailable(pixmap: object, quality: int) -> bytes:
        raise ValueError("no jpeg output")

    def tracked(pixmap: object, quality: int) -> bytes:
        used.append(1)
        return real_pillow(pixmap, quality)

    monkeypatch.setattr(engine, "_pixmap_jpeg", unavailable)
    monkeypatch.setattr(engine, "_pillow_jpeg", tracked)
    source = pdf_factory(tmp_path / "one.pdf", pages=1)
    out = _out(tmp_path)

    convert_pdf_to_jpg(source, out, "medium")

    assert used
    _jpeg_size((out / "result.jpg").read_bytes())


def test_concurrency_limit_is_enforced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MAX_CONCURRENT_JOBS", "2")
    get_settings.cache_clear()
    engine.rebuild_concurrency_gate()

    lock = threading.Lock()
    release = threading.Event()
    state = {"active": 0, "peak": 0, "entered": 0}

    def fake(input_path: Path, output_dir: Path, quality: str) -> PdfToJpgResult:
        with lock:
            state["active"] += 1
            state["entered"] += 1
            state["peak"] = max(state["peak"], state["active"])
        try:
            release.wait(timeout=10)
        finally:
            with lock:
                state["active"] -= 1
        return PdfToJpgResult(1, 1, 1, "jpg", "result.jpg")

    monkeypatch.setattr(engine, "_convert_locked", fake)
    threads = [
        threading.Thread(
            target=convert_pdf_to_jpg,
            args=(tmp_path / "in.pdf", tmp_path / "out", "low"),
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


def test_parse_quality_accepts_only_the_three_qualities() -> None:
    for quality in QUALITIES:
        assert parse_quality(quality) == quality
    for bad in ("High", "", "ultra", None, 1):
        with pytest.raises(AppError) as info:
            parse_quality(bad)
        assert info.value.code == INVALID_QUALITY


# -- Route ---------------------------------------------------------------------


def test_multi_page_success_returns_every_contract_field(
    post_pdf_to_jpg: PostPdfToJpg,
    pdf_factory: PdfFactory,
    tmp_path: Path,
    storage_dir: Path,
) -> None:
    content = pdf_factory(tmp_path / "three.pdf", pages=3).read_bytes()

    response = post_pdf_to_jpg(
        content, quality="medium", filename="Quarterly report.pdf"
    )

    assert response.status_code == 200
    body = response.json()
    assert set(body) == CONTRACT_FIELDS
    assert body["original_name"] == "Quarterly report"
    assert body["page_count"] == 3
    assert body["file_count"] == 3
    assert body["kind"] == "zip"
    assert body["quality"] == "medium"
    assert body["download_url"] == f"/api/jobs/{body['job_id']}/download"

    output_dir = storage_dir / "outputs" / body["job_id"]
    assert (output_dir / "result.zip").stat().st_size == body["result_size"]
    meta = json.loads((output_dir / "meta.json").read_text(encoding="utf-8"))
    assert meta["result_name"] == "result.zip"
    assert meta["download_name"] == "Quarterly report-jpg.zip"
    assert meta["original_name"] == "Quarterly report"
    assert not (storage_dir / "uploads" / body["job_id"]).exists()


def test_single_page_response_is_a_jpg(
    post_pdf_to_jpg: PostPdfToJpg,
    pdf_factory: PdfFactory,
    tmp_path: Path,
    storage_dir: Path,
) -> None:
    content = pdf_factory(tmp_path / "one.pdf", pages=1).read_bytes()

    response = post_pdf_to_jpg(content, quality="low", filename="Scan.pdf")

    assert response.status_code == 200
    body = response.json()
    assert body["kind"] == "jpg"
    assert body["page_count"] == 1
    assert body["file_count"] == 1
    assert body["quality"] == "low"
    output_dir = storage_dir / "outputs" / body["job_id"]
    assert (output_dir / "result.jpg").stat().st_size == body["result_size"]
    meta = json.loads((output_dir / "meta.json").read_text(encoding="utf-8"))
    assert meta["result_name"] == "result.jpg"
    assert meta["download_name"] == "Scan.jpg"


@pytest.mark.parametrize("quality", ["ultra", "High", "", None])
def test_bad_or_missing_quality_gives_invalid_quality_and_creates_no_job(
    post_pdf_to_jpg: PostPdfToJpg,
    text_pdf: Path,
    job_entries: Callable[[], list[str]],
    quality: str | None,
) -> None:
    response = post_pdf_to_jpg(text_pdf.read_bytes(), quality=quality)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == INVALID_QUALITY
    assert job_entries() == []


def test_missing_file_field_is_invalid_request(client: TestClient) -> None:
    response = client.post("/api/pdf-to-jpg", data={"quality": "medium"})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == INVALID_REQUEST


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
    post_pdf_to_jpg: PostPdfToJpg,
    encrypted_pdf: Path,
    job_entries: Callable[[], list[str]],
) -> None:
    contents = {
        "not_pdf": b"this is plain text, not a pdf. " * 20,
        "encrypted": encrypted_pdf.read_bytes(),
        "corrupt": b"%PDF-1.7\n" + b"garbage " * 200,
        "empty": b"",
    }

    response = post_pdf_to_jpg(contents[kind])

    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    assert job_entries() == []


def test_too_many_pages_gives_413_and_leaves_no_files(
    post_pdf_to_jpg: PostPdfToJpg,
    pdf_factory: PdfFactory,
    tmp_path: Path,
    job_entries: Callable[[], list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MAX_PDF_PAGES", "2")
    get_settings.cache_clear()
    content = pdf_factory(tmp_path / "three.pdf", pages=3).read_bytes()

    response = post_pdf_to_jpg(content)

    assert response.status_code == 413
    assert response.json()["error"]["code"] == TOO_MANY_PAGES
    assert job_entries() == []


def test_upload_just_over_the_limit_is_too_large(
    post_pdf_to_jpg: PostPdfToJpg,
    job_entries: Callable[[], list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MAX_UPLOAD_MB", "1")
    get_settings.cache_clear()
    content = b"%PDF-" + b"0" * (1024 * 1024 - 4)  # exactly 1 MiB + 1 byte
    assert len(content) == 1024 * 1024 + 1

    response = post_pdf_to_jpg(content)

    assert response.status_code == 413
    error = response.json()["error"]
    assert error["code"] == TOO_LARGE
    assert "1 MB" in error["message"]
    assert job_entries() == []


def test_engine_failure_returns_processing_failed_without_details(
    post_pdf_to_jpg: PostPdfToJpg,
    text_pdf: Path,
    job_entries: Callable[[], list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def explode(input_path: Path, output_dir: Path, quality: str) -> PdfToJpgResult:
        raise RuntimeError("boom at /secret/path")

    monkeypatch.setattr(engine, "_convert_locked", explode)

    response = post_pdf_to_jpg(text_pdf.read_bytes())

    assert response.status_code == 500
    assert response.json()["error"]["code"] == PROCESSING_FAILED
    assert "secret" not in response.text
    assert job_entries() == []


def test_unexpected_error_returns_internal_error_and_cleans_up(
    post_pdf_to_jpg: PostPdfToJpg,
    text_pdf: Path,
    job_entries: Callable[[], list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def explode(*args: object, **kwargs: object) -> None:
        raise RuntimeError("boom at /secret/path")

    monkeypatch.setattr(pdf_to_jpg_route, "convert_pdf_to_jpg", explode)

    response = post_pdf_to_jpg(text_pdf.read_bytes())

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert "secret" not in response.text
    assert job_entries() == []