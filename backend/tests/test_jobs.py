"""Tests for the job routes and for behaviour that spans the whole API."""

import io
import os
import time
import zipfile
from collections.abc import Callable
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from httpx import Response

from app import main as main_module
from app.api.routes import compress as compress_route
from app.api.routes import jobs as jobs_route
from app.core.config import get_settings
from app.core.errors import (
    ERROR_STATUS,
    INTERNAL_ERROR,
    INVALID_LEVEL,
    INVALID_REQUEST,
    JOB_NOT_FOUND,
    NOT_PDF,
)
from app.main import app
from app.services import pdf_to_jpg as pdf_to_jpg_engine
from app.utils import storage

PostCompress = Callable[..., Response]

UNKNOWN_ID = "0" * 32
INVALID_IDS = ["abc", "A" * 32, "g" * 32, "0" * 31, "0" * 33]


def _wait_until(predicate: Callable[[], bool], timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


def _make_job(
    post_compress: PostCompress, pdf: Path, filename: str = "report.pdf"
) -> dict[str, object]:
    response = post_compress(pdf.read_bytes(), filename=filename)
    assert response.status_code == 200
    return response.json()


# -- Download and delete -------------------------------------------------------


def test_download_has_the_contract_headers_and_deletes_the_job(
    client: TestClient,
    post_compress: PostCompress,
    text_pdf: Path,
    job_entries: Callable[[], list[str]],
) -> None:
    job = _make_job(post_compress, text_pdf)

    response = client.get(str(job["download_url"]))

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["content-disposition"] == (
        'attachment; filename="report-compressed.pdf"'
    )
    assert response.content.startswith(b"%PDF-")
    assert len(response.content) == job["compressed_size"]
    assert job_entries() == []


def test_non_ascii_names_are_encoded_in_the_filename_star_form(
    client: TestClient, post_compress: PostCompress, text_pdf: Path
) -> None:
    job = _make_job(post_compress, text_pdf, filename="Résumé final.pdf")

    response = client.get(str(job["download_url"]))

    assert response.status_code == 200
    assert (
        "filename*=utf-8''R%C3%A9sum%C3%A9%20final-compressed.pdf"
        in response.headers["content-disposition"]
    )


def test_second_download_is_job_not_found(
    client: TestClient, post_compress: PostCompress, text_pdf: Path
) -> None:
    job = _make_job(post_compress, text_pdf)
    assert client.get(str(job["download_url"])).status_code == 200

    second = client.get(str(job["download_url"]))

    assert second.status_code == 404
    assert second.json()["error"]["code"] == JOB_NOT_FOUND


def test_range_request_gets_the_whole_file_and_then_deletes_the_job(
    client: TestClient,
    post_compress: PostCompress,
    text_pdf: Path,
    job_entries: Callable[[], list[str]],
) -> None:
    job = _make_job(post_compress, text_pdf)

    response = client.get(str(job["download_url"]), headers={"Range": "bytes=0-9"})

    assert response.status_code == 200
    assert len(response.content) == job["compressed_size"]
    assert job_entries() == []


def test_head_is_not_answered_and_does_not_delete_the_job(
    client: TestClient, post_compress: PostCompress, text_pdf: Path
) -> None:
    job = _make_job(post_compress, text_pdf)

    head = client.head(str(job["download_url"]))

    assert head.status_code == 405
    assert client.get(str(job["download_url"])).status_code == 200


def test_unknown_but_well_formed_id(client: TestClient) -> None:
    download = client.get(f"/api/jobs/{UNKNOWN_ID}/download")
    removal = client.delete(f"/api/jobs/{UNKNOWN_ID}")

    assert download.status_code == 404
    assert download.json()["error"]["code"] == JOB_NOT_FOUND
    assert removal.status_code == 204


def test_download_with_invalid_ids_never_touches_the_disk(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(*args: object, **kwargs: object) -> Path:
        raise AssertionError("the disk was touched")

    monkeypatch.setattr(storage, "_kind_root", forbidden)

    for job_id in INVALID_IDS:
        response = client.get(f"/api/jobs/{job_id}/download")
        assert response.status_code == 404, job_id
        assert response.json()["error"]["code"] == JOB_NOT_FOUND


def test_delete_with_invalid_ids_never_touches_the_disk(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(*args: object, **kwargs: object) -> Path:
        raise AssertionError("the disk was touched")

    monkeypatch.setattr(storage, "_kind_root", forbidden)

    for job_id in INVALID_IDS:
        response = client.delete(f"/api/jobs/{job_id}")
        assert response.status_code == 204, job_id


def test_delete_is_204_every_time_and_removes_the_job(
    client: TestClient,
    post_compress: PostCompress,
    text_pdf: Path,
    job_entries: Callable[[], list[str]],
) -> None:
    job = _make_job(post_compress, text_pdf)
    url = f"/api/jobs/{job['job_id']}"

    first = client.delete(url)
    second = client.delete(url)

    assert first.status_code == 204
    assert first.content == b""
    assert second.status_code == 204
    assert job_entries() == []
    assert client.get(str(job["download_url"])).status_code == 404


# -- Cross-cutting -------------------------------------------------------------


def test_every_error_response_has_the_contract_shape(
    client: TestClient,
    post_compress: PostCompress,
    storage_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cases: list[tuple[Response, str]] = [
        (post_compress(b"definitely not a pdf"), NOT_PDF),
        (post_compress(b"%PDF-1.4", level="huge"), INVALID_LEVEL),
        (client.post("/api/compress", data={"level": "balanced"}), INVALID_REQUEST),
        (client.get(f"/api/jobs/{UNKNOWN_ID}/download"), JOB_NOT_FOUND),
    ]

    def explode(*args: object, **kwargs: object) -> None:
        raise RuntimeError("secret detail")

    monkeypatch.setattr(compress_route, "compress_pdf", explode)
    cases.append((post_compress(b"%PDF-1.4\n%%EOF"), INTERNAL_ERROR))

    for response, code in cases:
        body = response.json()
        assert set(body) == {"error"}, code
        assert set(body["error"]) == {"code", "message"}, code
        assert body["error"]["code"] == code
        assert response.status_code == ERROR_STATUS[code]
        assert isinstance(body["error"]["message"], str) and body["error"]["message"]
        assert "Traceback" not in response.text
        assert "secret" not in response.text
        assert str(storage_dir) not in response.text


def test_startup_empties_storage(storage_dir: Path) -> None:
    (storage_dir / "uploads" / "left-over").mkdir(parents=True)
    (storage_dir / "uploads" / "left-over" / "input.pdf").write_bytes(b"%PDF-")
    (storage_dir / "outputs" / "another").mkdir(parents=True)
    (storage_dir / "outputs" / "another" / "result.pdf").write_bytes(b"%PDF-")

    with TestClient(app, raise_server_exceptions=False):
        pass

    assert list((storage_dir / "uploads").iterdir()) == []
    assert list((storage_dir / "outputs").iterdir()) == []


def test_sweeper_removes_expired_jobs_and_keeps_fresh_ones(
    storage_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(main_module, "SWEEP_INTERVAL_SECONDS", 0.05)

    with TestClient(app, raise_server_exceptions=False):
        stale = storage_dir / "outputs" / ("a" * 32)
        fresh = storage_dir / "outputs" / ("b" * 32)
        stale.mkdir()
        fresh.mkdir()
        old = time.time() - 3600  # the default TTL is 30 minutes
        os.utime(stale, (old, old))

        assert _wait_until(lambda: not stale.exists())
        assert fresh.exists()


def test_sweeper_survives_an_exception(
    storage_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[int] = []

    def flaky() -> int:
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("boom")
        return 0

    monkeypatch.setattr(main_module, "SWEEP_INTERVAL_SECONDS", 0.05)
    monkeypatch.setattr(main_module, "sweep_expired", flaky)

    with TestClient(app, raise_server_exceptions=False):
        assert _wait_until(lambda: len(calls) >= 2)


@pytest.mark.parametrize("method", ["DELETE", "POST"])
def test_preflight_allows_the_frontend_origin(
    client: TestClient, method: str
) -> None:
    origin = get_settings().frontend_origin

    response = client.options(
        f"/api/jobs/{UNKNOWN_ID}",
        headers={"Origin": origin, "Access-Control-Request-Method": method},
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin
    assert method in response.headers["access-control-allow-methods"]


def test_another_origin_is_rejected(client: TestClient) -> None:
    evil = "http://evil.example"

    preflight = client.options(
        f"/api/jobs/{UNKNOWN_ID}",
        headers={"Origin": evil, "Access-Control-Request-Method": "DELETE"},
    )
    simple = client.get("/api/health", headers={"Origin": evil})

    assert preflight.status_code == 400
    assert "access-control-allow-origin" not in preflight.headers
    assert "access-control-allow-origin" not in simple.headers


# -- Result types (Phase 2) ----------------------------------------------------

PostPdfToJpg = Callable[..., Response]
PdfFactory = Callable[..., Path]


def _store_job(content: bytes, file_name: str, meta: dict[str, object] | None) -> str:
    """Put a finished job on disk by hand, the way a route would leave it."""
    job_id = storage.new_job_id()
    output_dir = storage.get_output_dir(job_id, create=True)
    (output_dir / file_name).write_bytes(content)
    if meta is not None:
        storage.write_meta(job_id, meta)
    return job_id


def test_zip_result_has_the_zip_headers_and_deletes_the_job(
    client: TestClient,
    post_pdf_to_jpg: PostPdfToJpg,
    pdf_factory: PdfFactory,
    tmp_path: Path,
    job_entries: Callable[[], list[str]],
) -> None:
    source = pdf_factory(tmp_path / "three.pdf", pages=3)
    job = post_pdf_to_jpg(source.read_bytes(), filename="report.pdf").json()

    response = client.get(str(job["download_url"]))

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["content-disposition"] == (
        'attachment; filename="report-jpg.zip"'
    )
    assert zipfile.is_zipfile(io.BytesIO(response.content))
    assert len(response.content) == job["result_size"]
    assert job_entries() == []


def test_jpg_result_has_the_jpeg_headers_and_deletes_the_job(
    client: TestClient,
    post_pdf_to_jpg: PostPdfToJpg,
    pdf_factory: PdfFactory,
    tmp_path: Path,
    job_entries: Callable[[], list[str]],
) -> None:
    source = pdf_factory(tmp_path / "one.pdf", pages=1)
    job = post_pdf_to_jpg(source.read_bytes(), filename="report.pdf").json()

    response = client.get(str(job["download_url"]))

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["content-disposition"] == (
        'attachment; filename="report.jpg"'
    )
    assert response.content.startswith(b"\xff\xd8\xff")
    assert len(response.content) == job["result_size"]
    assert job_entries() == []


def test_a_converted_job_cannot_be_downloaded_twice(
    client: TestClient,
    post_pdf_to_jpg: PostPdfToJpg,
    pdf_factory: PdfFactory,
    tmp_path: Path,
) -> None:
    source = pdf_factory(tmp_path / "three.pdf", pages=3)
    job = post_pdf_to_jpg(source.read_bytes()).json()
    assert client.get(str(job["download_url"])).status_code == 200

    second = client.get(str(job["download_url"]))

    assert second.status_code == 404
    assert second.json()["error"]["code"] == JOB_NOT_FOUND


def test_range_request_on_a_zip_gets_the_whole_file_and_deletes_the_job(
    client: TestClient,
    post_pdf_to_jpg: PostPdfToJpg,
    pdf_factory: PdfFactory,
    tmp_path: Path,
    job_entries: Callable[[], list[str]],
) -> None:
    source = pdf_factory(tmp_path / "three.pdf", pages=3)
    job = post_pdf_to_jpg(source.read_bytes()).json()

    response = client.get(str(job["download_url"]), headers={"Range": "bytes=0-9"})

    assert response.status_code == 200
    assert len(response.content) == job["result_size"]
    assert job_entries() == []


def test_a_phase_1_job_without_the_new_meta_keys_downloads_as_before(
    client: TestClient, job_entries: Callable[[], list[str]]
) -> None:
    content = b"%PDF-1.4 legacy result"
    job_id = _store_job(content, "result.pdf", {"original_name": "legacy"})

    response = client.get(f"/api/jobs/{job_id}/download")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"] == (
        'attachment; filename="legacy-compressed.pdf"'
    )
    assert response.content == content
    assert job_entries() == []


def test_a_job_without_any_metadata_falls_back_to_a_generic_name(
    client: TestClient,
) -> None:
    job_id = _store_job(b"%PDF-1.4 no meta", "result.pdf", None)

    response = client.get(f"/api/jobs/{job_id}/download")

    assert response.status_code == 200
    assert response.headers["content-disposition"] == (
        'attachment; filename="document-compressed.pdf"'
    )


@pytest.mark.parametrize(
    "bad_name",
    ["result.exe", "../result.pdf", "meta.json", "RESULT.PDF", "", 7],
)
def test_a_result_name_outside_the_allowlist_is_job_not_found(
    client: TestClient, bad_name: object
) -> None:
    job_id = _store_job(
        b"%PDF-1.4 secret",
        "result.pdf",
        {"original_name": "x", "result_name": bad_name, "download_name": "x.pdf"},
    )

    response = client.get(f"/api/jobs/{job_id}/download")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == JOB_NOT_FOUND
    assert b"secret" not in response.content


def test_a_stored_download_name_is_sanitised_and_keeps_the_fixed_extension(
    client: TestClient,
) -> None:
    job_id = _store_job(
        b"PK\x03\x04 zip-ish bytes",
        "result.zip",
        {
            "original_name": "x",
            "result_name": "result.zip",
            "download_name": "..\\..\\evil name.exe",
        },
    )

    response = client.get(f"/api/jobs/{job_id}/download")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    disposition = response.headers["content-disposition"]
    assert "evil%20name.zip" in disposition
    assert ".." not in disposition
    assert "\\" not in disposition
    assert ".exe" not in disposition


def test_engine_result_names_match_the_download_allowlist() -> None:
    assert dict(jobs_route.RESULT_TYPES) == {
        "result.pdf": ("application/pdf", ".pdf"),
        "result.jpg": ("image/jpeg", ".jpg"),
        "result.zip": ("application/zip", ".zip"),
        "result.docx": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", ".docx"),
    }
    assert pdf_to_jpg_engine.RESULT_JPG in jobs_route.RESULT_TYPES
    assert pdf_to_jpg_engine.RESULT_ZIP in jobs_route.RESULT_TYPES


def test_startup_empties_a_leftover_conversion_job(
    storage_dir: Path, pdf_factory: PdfFactory, tmp_path: Path
) -> None:
    content = pdf_factory(tmp_path / "three.pdf", pages=3).read_bytes()
    with TestClient(app, raise_server_exceptions=False) as first:
        response = first.post(
            "/api/pdf-to-jpg",
            files={"file": ("report.pdf", content, "application/pdf")},
            data={"quality": "low"},
        )
        job_id = response.json()["job_id"]
    assert (storage_dir / "outputs" / job_id).exists()

    with TestClient(app, raise_server_exceptions=False):
        pass

    assert not (storage_dir / "outputs" / job_id).exists()
    
def test_a_phase_1_name_with_a_dot_keeps_it_in_the_download_name(
    client: TestClient,
) -> None:
    job_id = _store_job(
        b"%PDF-1.4 dotted", "result.pdf", {"original_name": "report.v2"}
    )

    response = client.get(f"/api/jobs/{job_id}/download")

    assert response.status_code == 200
    assert response.headers["content-disposition"] == (
        'attachment; filename="report.v2-compressed.pdf"'
    )
