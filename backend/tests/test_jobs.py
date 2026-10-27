"""Tests for the job routes and for behaviour that spans the whole API."""

import os
import time
from collections.abc import Callable
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from httpx import Response

from app import main as main_module
from app.api.routes import compress as compress_route
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