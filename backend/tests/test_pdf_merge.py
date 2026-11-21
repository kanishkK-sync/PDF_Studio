"""Tests for the PDF merge engine and POST /api/merge."""

import json
import threading
import time
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path

import pymupdf
import pytest
from fastapi.testclient import TestClient
from httpx import Response

from app.api.routes import jobs as jobs_route
from app.api.routes import merge as merge_route
from app.core.config import get_settings
from app.core.errors import (
    CORRUPT,
    ENCRYPTED,
    INTERNAL_ERROR,
    INVALID_REQUEST,
    NOT_PDF,
    TOO_LARGE,
    TOO_MANY_FILES,
    TOO_MANY_PAGES,
    AppError,
)
from app.services import pdf_merge as engine
from app.services.pdf_merge import PdfMergeResult, merge_pdfs

PostMerge = Callable[..., Response]

CONTRACT_FIELDS = {
    "job_id",
    "file_count",
    "page_count",
    "total_input_size",
    "result_size",
    "download_name",
    "download_url",
}


@pytest.fixture(autouse=True)
def _reset_pdf_merge_gate() -> Iterator[None]:
    """Rebuild this engine's gate after every test in this module."""
    yield
    get_settings.cache_clear()
    engine.rebuild_concurrency_gate()


@pytest.fixture
def post_merge(client: TestClient) -> PostMerge:
    def _post(
        files: Sequence[tuple[str, bytes]],
    ) -> Response:
        return client.post(
            "/api/merge",
            files=[
                ("files", (name, content, "application/pdf"))
                for name, content in files
            ],
        )

    return _post


def _out(tmp_path: Path) -> Path:
    folder = tmp_path / "out"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _wait_until(predicate: Callable[[], bool], timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def _make_pdf(
    path: Path,
    pages_text: list[str],
    toc: list[list[object]] | None = None,
) -> Path:
    doc = pymupdf.open()
    try:
        for text in pages_text:
            page = doc.new_page(width=300, height=300)
            page.insert_text((50, 50), text)
        if toc:
            doc.set_toc(toc)
        doc.save(str(path))
    finally:
        doc.close()
    return path


def _page_texts(path: Path) -> list[str]:
    doc = pymupdf.open(str(path))
    try:
        return [page.get_text().strip() for page in doc]
    finally:
        doc.close()


# -- Engine tests --------------------------------------------------------------


def test_merge_page_order_and_text_preserved_across_three_files(
    tmp_path: Path,
) -> None:
    f1 = _make_pdf(tmp_path / "a.pdf", ["Doc A Page 1", "Doc A Page 2"])
    f2 = _make_pdf(tmp_path / "b.pdf", ["Doc B Page 1"])
    f3 = _make_pdf(tmp_path / "c.pdf", ["Doc C Page 1", "Doc C Page 2"])

    out = _out(tmp_path)
    result = merge_pdfs([f1, f2, f3], out)

    assert result.file_count == 3
    assert result.page_count == 5
    assert result.result_name == "result.pdf"
    assert (out / "result.pdf").stat().st_size == result.result_size

    texts = _page_texts(out / "result.pdf")
    assert texts == [
        "Doc A Page 1",
        "Doc A Page 2",
        "Doc B Page 1",
        "Doc C Page 1",
        "Doc C Page 2",
    ]


def test_merge_preserves_bookmarks_with_shifted_pages(tmp_path: Path) -> None:
    f1 = _make_pdf(
        tmp_path / "a.pdf",
        ["Doc A P1", "Doc A P2"],
        toc=[[1, "Chapter A", 1], [2, "Section A1", 2]],
    )
    f2 = _make_pdf(
        tmp_path / "b.pdf",
        ["Doc B P1"],
        toc=[[1, "Chapter B", 1]],
    )

    out = _out(tmp_path)
    result = merge_pdfs([f1, f2], out)
    assert result.page_count == 3

    merged_doc = pymupdf.open(str(out / "result.pdf"))
    try:
        toc = merged_doc.get_toc()
        assert toc == [
            [1, "Chapter A", 1],
            [2, "Section A1", 2],
            [1, "Chapter B", 3],
        ]
    finally:
        merged_doc.close()


def test_merge_encrypted_pdf_reports_position(
    tmp_path: Path, encrypted_pdf: Path
) -> None:
    f1 = _make_pdf(tmp_path / "a.pdf", ["Valid Page"])
    out = _out(tmp_path)

    with pytest.raises(AppError) as info:
        merge_pdfs([f1, encrypted_pdf], out)

    assert info.value.code == ENCRYPTED
    assert "File 2" in info.value.message


def test_merge_corrupt_pdf_reports_position(tmp_path: Path) -> None:
    f1 = _make_pdf(tmp_path / "a.pdf", ["Valid Page"])
    corrupt = tmp_path / "corrupt.pdf"
    corrupt.write_bytes(b"%PDF-1.7\nnot a real pdf content")
    out = _out(tmp_path)

    with pytest.raises(AppError) as info:
        merge_pdfs([f1, corrupt], out)

    assert info.value.code == CORRUPT
    assert "file 2" in info.value.message


def test_merge_summed_pages_over_limit_raises_too_many_pages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MAX_PDF_PAGES", "3")
    get_settings.cache_clear()
    engine.rebuild_concurrency_gate()

    f1 = _make_pdf(tmp_path / "a.pdf", ["P1", "P2"])
    f2 = _make_pdf(tmp_path / "b.pdf", ["P3", "P4"])
    out = _out(tmp_path)

    with pytest.raises(AppError) as info:
        merge_pdfs([f1, f2], out)

    assert info.value.code == TOO_MANY_PAGES
    assert "4 pages" in info.value.message
    assert "3" in info.value.message


def test_merge_concurrency_limit_is_enforced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MAX_CONCURRENT_JOBS", "2")
    get_settings.cache_clear()
    engine.rebuild_concurrency_gate()

    lock = threading.Lock()
    release = threading.Event()
    state = {"active": 0, "peak": 0, "entered": 0}

    def fake(input_paths: list[Path], output_dir: Path) -> PdfMergeResult:
        with lock:
            state["active"] += 1
            state["entered"] += 1
            state["peak"] = max(state["peak"], state["active"])
        try:
            release.wait(timeout=10)
        finally:
            with lock:
                state["active"] -= 1
        return PdfMergeResult(2, 2, 100, "result.pdf")

    monkeypatch.setattr(engine, "_merge_locked", fake)
    threads = [
        threading.Thread(
            target=merge_pdfs,
            args=([tmp_path / "a.pdf", tmp_path / "b.pdf"], tmp_path / "out"),
        )
        for _ in range(3)
    ]
    for thread in threads:
        thread.start()
    try:
        assert _wait_until(lambda: state["entered"] == 1)
        time.sleep(0.3)
        assert state["entered"] == 1
        release.set()
        assert _wait_until(lambda: state["entered"] == 3)
    finally:
        release.set()
        for thread in threads:
            thread.join(timeout=10)

    assert state["peak"] == 1


def test_merge_result_name_in_download_allowlist() -> None:
    assert engine.RESULT_PDF in jobs_route.RESULT_TYPES
    assert jobs_route.RESULT_TYPES[engine.RESULT_PDF][0] == "application/pdf"


# -- Route tests ---------------------------------------------------------------


def test_merge_route_success_returns_contract_fields(
    client: TestClient,
    post_merge: PostMerge,
    storage_dir: Path,
    tmp_path: Path,
) -> None:
    p1 = _make_pdf(tmp_path / "1.pdf", ["Page 1"]).read_bytes()
    p2 = _make_pdf(tmp_path / "2.pdf", ["Page 2"]).read_bytes()
    files = [("doc1.pdf", p1), ("doc2.pdf", p2)]

    response = post_merge(files)
    assert response.status_code == 200
    body = response.json()

    assert set(body) == CONTRACT_FIELDS
    assert body["file_count"] == 2
    assert body["page_count"] == 2
    assert body["total_input_size"] == len(p1) + len(p2)
    assert body["download_name"] == "merged.pdf"
    assert body["download_url"] == f"/api/jobs/{body['job_id']}/download"

    output_dir = storage_dir / "outputs" / body["job_id"]
    assert (output_dir / "result.pdf").stat().st_size == body["result_size"]
    meta = json.loads((output_dir / "meta.json").read_text(encoding="utf-8"))
    assert meta["result_name"] == "result.pdf"
    assert meta["download_name"] == "merged.pdf"
    assert meta["file_count"] == 2
    assert meta["page_count"] == 2
    assert not (storage_dir / "uploads" / body["job_id"]).exists()

    download = client.get(body["download_url"])
    assert download.status_code == 200
    assert download.headers["content-type"] == "application/pdf"
    assert "no-store" in download.headers.get("cache-control", "")
    assert 'filename="merged.pdf"' in download.headers.get(
        "content-disposition", ""
    )

    # Second GET is 404
    second = client.get(body["download_url"])
    assert second.status_code == 404
    assert second.json()["error"]["code"] == "job_not_found"


def test_merge_fewer_than_two_files_gives_invalid_request(
    post_merge: PostMerge,
    tmp_path: Path,
    job_entries: Callable[[], list[str]],
) -> None:
    p1 = _make_pdf(tmp_path / "1.pdf", ["Page 1"]).read_bytes()
    response = post_merge([("only_one.pdf", p1)])

    assert response.status_code == 422
    assert response.json()["error"]["code"] == INVALID_REQUEST
    assert "at least two" in response.json()["error"]["message"]
    assert job_entries() == []


def test_merge_more_than_max_merge_files_gives_too_many_files(
    post_merge: PostMerge,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    job_entries: Callable[[], list[str]],
) -> None:
    monkeypatch.setenv("MAX_MERGE_FILES", "2")
    get_settings.cache_clear()

    p = _make_pdf(tmp_path / "doc.pdf", ["Page"]).read_bytes()
    response = post_merge([("1.pdf", p), ("2.pdf", p), ("3.pdf", p)])

    assert response.status_code == 413
    assert response.json()["error"]["code"] == TOO_MANY_FILES
    assert "2" in response.json()["error"]["message"]
    assert job_entries() == []


def test_merge_total_size_over_limit_gives_too_large(
    post_merge: PostMerge,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    job_entries: Callable[[], list[str]],
) -> None:
    monkeypatch.setenv("MAX_UPLOAD_MB", "1")
    get_settings.cache_clear()

    # 2 files totaling over 1MB
    half_mb = b"%PDF-1.4\n" + b"0" * (600 * 1024)
    response = post_merge([("1.pdf", half_mb), ("2.pdf", half_mb)])

    assert response.status_code == 413
    assert response.json()["error"]["code"] == TOO_LARGE
    assert "1 MB" in response.json()["error"]["message"]
    assert job_entries() == []


def test_merge_non_pdf_names_its_position(
    post_merge: PostMerge,
    tmp_path: Path,
    job_entries: Callable[[], list[str]],
) -> None:
    p1 = _make_pdf(tmp_path / "1.pdf", ["Page 1"]).read_bytes()
    bad = b"This is plain text and definitely not a PDF file."
    response = post_merge([("1.pdf", p1), ("2.txt", bad)])

    assert response.status_code == 400
    assert response.json()["error"]["code"] == NOT_PDF
    assert "File 2" in response.json()["error"]["message"]
    assert job_entries() == []


def test_merge_empty_file_names_its_position(
    post_merge: PostMerge,
    tmp_path: Path,
    job_entries: Callable[[], list[str]],
) -> None:
    p1 = _make_pdf(tmp_path / "1.pdf", ["Page 1"]).read_bytes()
    response = post_merge([("1.pdf", p1), ("empty.pdf", b"")])

    assert response.status_code == 400
    assert response.json()["error"]["code"] == NOT_PDF
    assert "File 2" in response.json()["error"]["message"]
    assert "empty" in response.json()["error"]["message"]
    assert job_entries() == []


def test_merge_unexpected_error_gives_500_internal_error(
    post_merge: PostMerge,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    job_entries: Callable[[], list[str]],
) -> None:
    def boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("boom at /secret/folder/path")

    monkeypatch.setattr(merge_route, "merge_pdfs", boom)

    p1 = _make_pdf(tmp_path / "1.pdf", ["P1"]).read_bytes()
    p2 = _make_pdf(tmp_path / "2.pdf", ["P2"]).read_bytes()
    response = post_merge([("1.pdf", p1), ("2.pdf", p2)])

    assert response.status_code == 500
    assert response.json()["error"]["code"] == INTERNAL_ERROR
    assert "secret" not in response.text
    assert job_entries() == []
