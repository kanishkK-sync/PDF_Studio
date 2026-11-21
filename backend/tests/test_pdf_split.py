"""Tests for the PDF split engine and POST /api/split."""

import json
import threading
import time
import zipfile
from collections.abc import Callable, Iterator
from pathlib import Path

import pymupdf
import pytest
from fastapi.testclient import TestClient
from httpx import Response

from app.api.routes import jobs as jobs_route
from app.api.routes import split as split_route
from app.core.config import get_settings
from app.core.errors import (
    CORRUPT,
    ENCRYPTED,
    INTERNAL_ERROR,
    INVALID_RANGES,
    INVALID_REQUEST,
    NOT_PDF,
    TOO_LARGE,
    TOO_MANY_PAGES,
    AppError,
)
from app.services import pdf_split as engine
from app.services.pdf_split import PdfSplitResult, parse_ranges, split_pdf

PostSplit = Callable[..., Response]

CONTRACT_FIELDS = {
    "job_id",
    "original_name",
    "page_count",
    "selected_pages",
    "file_count",
    "kind",
    "mode",
    "result_size",
    "download_name",
    "download_url",
}


@pytest.fixture(autouse=True)
def _reset_pdf_split_gate() -> Iterator[None]:
    """Rebuild this engine's gate after every test in this module."""
    yield
    get_settings.cache_clear()
    engine.rebuild_concurrency_gate()


@pytest.fixture
def post_split(client: TestClient) -> PostSplit:
    def _post(
        content: bytes,
        *,
        ranges: str = "1",
        mode: str = "extract",
        filename: str = "report.pdf",
        content_type: str = "application/pdf",
    ) -> Response:
        return client.post(
            "/api/split",
            files={"file": (filename, content, content_type)},
            data={"ranges": ranges, "mode": mode},
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


def _make_pdf(path: Path, pages_text: list[str]) -> Path:
    doc = pymupdf.open()
    try:
        for text in pages_text:
            page = doc.new_page(width=300, height=300)
            page.insert_text((50, 50), text)
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


# -- Parser tests --------------------------------------------------------------


@pytest.mark.parametrize(
    ("input_text", "expected"),
    [
        ("1", [(1, 1)]),
        ("1-3", [(1, 3)]),
        ("2-", [(2, None)]),
        ("1-3, 5,7-9", [(1, 3), (5, 5), (7, 9)]),
        ("  1 - 2 ,  4  , 6- ", [(1, 2), (4, 4), (6, None)]),
    ],
)
def test_parse_ranges_valid_cases(
    input_text: str, expected: list[tuple[int, int | None]]
) -> None:
    assert parse_ranges(input_text) == expected


@pytest.mark.parametrize(
    "bad_text",
    [
        "",
        "   ",
        "0",
        "3-1",
        "a",
        "1--2",
        "1,,2",
        ",1",
        "1,",
        ",".join(str(i) for i in range(1, 102)),
        "1000000",
    ],
)
def test_parse_ranges_invalid_cases(bad_text: str) -> None:
    with pytest.raises(AppError) as info:
        parse_ranges(bad_text)
    assert info.value.code == INVALID_RANGES


# -- Engine tests --------------------------------------------------------------


def test_split_extract_mode_preserves_pages_and_repeats(tmp_path: Path) -> None:
    pdf = _make_pdf(
        tmp_path / "in.pdf",
        ["Page 1", "Page 2", "Page 3", "Page 4"],
    )
    out = _out(tmp_path)
    ranges = parse_ranges("3, 1, 3, 2-4")

    result = split_pdf(pdf, out, ranges, "extract")

    assert result.page_count == 4
    assert result.selected_pages == 6
    assert result.file_count == 1
    assert result.kind == "pdf"
    assert result.result_name == "result.pdf"

    extracted_texts = _page_texts(out / "result.pdf")
    assert extracted_texts == [
        "Page 3",
        "Page 1",
        "Page 3",
        "Page 2",
        "Page 3",
        "Page 4",
    ]


def test_split_separate_mode_builds_zip_with_valid_parts(tmp_path: Path) -> None:
    pdf = _make_pdf(
        tmp_path / "in.pdf",
        ["P1", "P2", "P3", "P4", "P5"],
    )
    out = _out(tmp_path)
    ranges = parse_ranges("1, 2-3, 5-")

    result = split_pdf(pdf, out, ranges, "separate")

    assert result.page_count == 5
    assert result.selected_pages == 4
    assert result.file_count == 3
    assert result.kind == "zip"
    assert result.result_name == "result.zip"

    zip_path = out / "result.zip"
    with zipfile.ZipFile(zip_path, "r") as archive:
        names = archive.namelist()
        assert names == ["part-001.pdf", "part-002.pdf", "part-003.pdf"]

        part1_bytes = archive.read("part-001.pdf")
        d1 = pymupdf.open(stream=part1_bytes, filetype="pdf")
        assert d1.page_count == 1
        assert d1[0].get_text().strip() == "P1"
        d1.close()

        part2_bytes = archive.read("part-002.pdf")
        d2 = pymupdf.open(stream=part2_bytes, filetype="pdf")
        assert d2.page_count == 2
        assert [p.get_text().strip() for p in d2] == ["P2", "P3"]
        d2.close()

        part3_bytes = archive.read("part-003.pdf")
        d3 = pymupdf.open(stream=part3_bytes, filetype="pdf")
        assert d3.page_count == 1
        assert d3[0].get_text().strip() == "P5"
        d3.close()


def test_split_page_above_page_count_raises_invalid_ranges(
    tmp_path: Path,
) -> None:
    pdf = _make_pdf(tmp_path / "in.pdf", ["P1", "P2"])
    out = _out(tmp_path)
    ranges = parse_ranges("1, 5")

    with pytest.raises(AppError) as info:
        split_pdf(pdf, out, ranges, "extract")

    assert info.value.code == INVALID_RANGES
    assert "2 pages" in info.value.message
    assert "5" in info.value.message


def test_split_concurrency_limit_is_enforced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MAX_CONCURRENT_JOBS", "2")
    get_settings.cache_clear()
    engine.rebuild_concurrency_gate()

    lock = threading.Lock()
    release = threading.Event()
    state = {"active": 0, "peak": 0, "entered": 0}

    def fake(
        input_path: Path,
        output_dir: Path,
        ranges: list[tuple[int, int | None]],
        mode: str,
    ) -> PdfSplitResult:
        with lock:
            state["active"] += 1
            state["entered"] += 1
            state["peak"] = max(state["peak"], state["active"])
        try:
            release.wait(timeout=10)
        finally:
            with lock:
                state["active"] -= 1
        return PdfSplitResult(2, 1, 1, "pdf", 100, "result.pdf")

    monkeypatch.setattr(engine, "_split_locked", fake)
    threads = [
        threading.Thread(
            target=split_pdf,
            args=(tmp_path / "in.pdf", tmp_path / "out", [(1, 1)], "extract"),
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


def test_split_result_names_in_download_allowlist() -> None:
    assert engine.RESULT_PDF in jobs_route.RESULT_TYPES
    assert engine.RESULT_ZIP in jobs_route.RESULT_TYPES
    assert jobs_route.RESULT_TYPES[engine.RESULT_PDF][0] == "application/pdf"
    assert jobs_route.RESULT_TYPES[engine.RESULT_ZIP][0] == "application/zip"


# -- Route tests ---------------------------------------------------------------


def test_split_route_extract_mode_contract_fields_and_download(
    client: TestClient,
    post_split: PostSplit,
    storage_dir: Path,
    tmp_path: Path,
) -> None:
    source = _make_pdf(tmp_path / "sample.pdf", ["P1", "P2", "P3"])
    response = post_split(
        source.read_bytes(),
        ranges="1, 3",
        mode="extract",
        filename="Doc.pdf",
    )

    assert response.status_code == 200
    body = response.json()
    assert set(body) == CONTRACT_FIELDS
    assert body["original_name"] == "Doc"
    assert body["page_count"] == 3
    assert body["selected_pages"] == 2
    assert body["file_count"] == 1
    assert body["kind"] == "pdf"
    assert body["mode"] == "extract"
    assert body["download_name"] == "Doc-pages.pdf"
    assert body["download_url"] == f"/api/jobs/{body['job_id']}/download"

    output_dir = storage_dir / "outputs" / body["job_id"]
    assert (output_dir / "result.pdf").stat().st_size == body["result_size"]
    meta = json.loads((output_dir / "meta.json").read_text(encoding="utf-8"))
    assert meta["result_name"] == "result.pdf"
    assert meta["download_name"] == "Doc-pages.pdf"
    assert not (storage_dir / "uploads" / body["job_id"]).exists()

    download = client.get(body["download_url"])
    assert download.status_code == 200
    assert download.headers["content-type"] == "application/pdf"
    assert 'filename="Doc-pages.pdf"' in download.headers.get(
        "content-disposition", ""
    )

    second = client.get(body["download_url"])
    assert second.status_code == 404


def test_split_route_separate_mode_contract_fields_and_download(
    client: TestClient,
    post_split: PostSplit,
    storage_dir: Path,
    tmp_path: Path,
) -> None:
    source = _make_pdf(tmp_path / "sample.pdf", ["P1", "P2", "P3"])
    response = post_split(
        source.read_bytes(),
        ranges="1-2, 3",
        mode="separate",
        filename="Doc.pdf",
    )

    assert response.status_code == 200
    body = response.json()
    assert set(body) == CONTRACT_FIELDS
    assert body["kind"] == "zip"
    assert body["mode"] == "separate"
    assert body["file_count"] == 2
    assert body["download_name"] == "Doc-split.zip"

    download = client.get(body["download_url"])
    assert download.status_code == 200
    assert download.headers["content-type"] == "application/zip"
    assert 'filename="Doc-split.zip"' in download.headers.get(
        "content-disposition", ""
    )

    second = client.get(body["download_url"])
    assert second.status_code == 404


def test_split_bad_mode_creates_no_job(
    post_split: PostSplit,
    tmp_path: Path,
    job_entries: Callable[[], list[str]],
) -> None:
    source = _make_pdf(tmp_path / "sample.pdf", ["P1"])
    response = post_split(source.read_bytes(), mode="invalid")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == INVALID_REQUEST
    assert "extract or separate" in response.json()["error"]["message"]
    assert job_entries() == []


def test_split_bad_syntax_creates_no_job(
    post_split: PostSplit,
    tmp_path: Path,
    job_entries: Callable[[], list[str]],
) -> None:
    source = _make_pdf(tmp_path / "sample.pdf", ["P1"])
    response = post_split(source.read_bytes(), ranges="abc")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == INVALID_RANGES
    assert job_entries() == []


def test_split_encrypted_pdf_gives_encrypted(
    post_split: PostSplit,
    encrypted_pdf: Path,
    job_entries: Callable[[], list[str]],
) -> None:
    response = post_split(encrypted_pdf.read_bytes())

    assert response.status_code == 400
    assert response.json()["error"]["code"] == ENCRYPTED
    assert job_entries() == []


def test_split_corrupt_pdf_gives_corrupt(
    post_split: PostSplit,
    job_entries: Callable[[], list[str]],
) -> None:
    corrupt = b"%PDF-1.4\ncorrupt not a valid pdf"
    response = post_split(corrupt)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == CORRUPT
    assert job_entries() == []


def test_split_empty_file_gives_not_pdf(
    post_split: PostSplit,
    job_entries: Callable[[], list[str]],
) -> None:
    response = post_split(b"")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == NOT_PDF
    assert job_entries() == []


def test_split_not_pdf_signature_gives_not_pdf(
    post_split: PostSplit,
    job_entries: Callable[[], list[str]],
) -> None:
    response = post_split(b"this is definitely not a pdf at all")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == NOT_PDF
    assert job_entries() == []


def test_split_too_many_pages_gives_too_many_pages(
    post_split: PostSplit,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    job_entries: Callable[[], list[str]],
) -> None:
    monkeypatch.setenv("MAX_PDF_PAGES", "2")
    get_settings.cache_clear()

    source = _make_pdf(tmp_path / "sample.pdf", ["P1", "P2", "P3"])
    response = post_split(source.read_bytes(), ranges="1")

    assert response.status_code == 413
    assert response.json()["error"]["code"] == TOO_MANY_PAGES
    assert job_entries() == []


def test_split_too_large_gives_too_large(
    post_split: PostSplit,
    monkeypatch: pytest.MonkeyPatch,
    job_entries: Callable[[], list[str]],
) -> None:
    monkeypatch.setenv("MAX_UPLOAD_MB", "1")
    get_settings.cache_clear()

    content = b"%PDF-1.4\n" + b"0" * (1024 * 1024 + 10)
    response = post_split(content)

    assert response.status_code == 413
    assert response.json()["error"]["code"] == TOO_LARGE
    assert job_entries() == []


def test_split_unexpected_error_gives_500_internal_error(
    post_split: PostSplit,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    job_entries: Callable[[], list[str]],
) -> None:
    def boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("boom at /secret/folder/path")

    monkeypatch.setattr(split_route, "split_pdf", boom)

    source = _make_pdf(tmp_path / "sample.pdf", ["P1"])
    response = post_split(source.read_bytes())

    assert response.status_code == 500
    assert response.json()["error"]["code"] == INTERNAL_ERROR
    assert "secret" not in response.text
    assert job_entries() == []

