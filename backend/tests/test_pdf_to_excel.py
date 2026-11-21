"""Tests for the PDF to Excel engine and POST /api/pdf-to-excel."""

import io
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
from openpyxl import load_workbook

from app.api.routes import pdf_to_excel as pdf_to_excel_route
from app.core.config import get_settings
from app.core.errors import (
    CORRUPT,
    ENCRYPTED,
    INVALID_REQUEST,
    JOB_NOT_FOUND,
    NO_CONTENT,
    NOT_PDF,
    PROCESSING_FAILED,
    TOO_LARGE,
    TOO_MANY_PAGES,
    AppError,
)
from app.services import pdf_to_excel as engine
from app.services.pdf_to_excel import PdfToExcelResult, convert_pdf_to_excel

PdfFactory = Callable[..., Path]
PostPdfToExcel = Callable[..., Response]

XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
CONTRACT_FIELDS = {
    "job_id",
    "original_name",
    "page_count",
    "table_count",
    "sheet_count",
    "mode",
    "original_size",
    "result_size",
    "download_name",
    "download_url",
}

# Where the grid starts on the page and how big each cell is, in points.
_GRID_LEFT = 72.0
_GRID_TOP = 100.0
_CELL_WIDTH = 120.0
_CELL_HEIGHT = 28.0

# A header row and two data rows. Short words, so every character of a cell
# sits inside its own cell and pdfplumber assigns the text to the right one.
TABLE = [
    ["Item", "Qty", "Price"],
    ["Apple", "3", "1.50"],
    ["Pear", "5", "2.25"],
]

# Each of these must fit a 120-point cell at 10 points, or its last characters
# would land in the next cell.
FORMULAS = ["=1+1", "=SUM(A1:A9)", '=HYPERLINK("x")']


@pytest.fixture(autouse=True)
def _reset_pdf_to_excel_gate() -> Iterator[None]:
    """Rebuild this engine's gate after every test in this module."""
    yield
    get_settings.cache_clear()
    engine.rebuild_concurrency_gate()


# -- Helpers -------------------------------------------------------------------


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


def _table_pdf(path: Path, tables: list[list[list[str]]]) -> Path:
    """One page per entry, each a ruled grid of real lines with the text inside.

    pdfplumber finds tables from ruling lines, so every cell is fully enclosed
    by drawn lines: the finder has nothing to guess.
    """
    document = pymupdf.open()
    try:
        for rows in tables:
            page = document.new_page(width=595, height=842)
            columns = max(len(row) for row in rows)
            right = _GRID_LEFT + columns * _CELL_WIDTH
            bottom = _GRID_TOP + len(rows) * _CELL_HEIGHT
            for line in range(len(rows) + 1):
                y = _GRID_TOP + line * _CELL_HEIGHT
                page.draw_line((_GRID_LEFT, y), (right, y))
            for line in range(columns + 1):
                x = _GRID_LEFT + line * _CELL_WIDTH
                page.draw_line((x, _GRID_TOP), (x, bottom))
            for row_number, row in enumerate(rows):
                for column, text in enumerate(row):
                    page.insert_text(
                        (
                            _GRID_LEFT + column * _CELL_WIDTH + 6,
                            _GRID_TOP + row_number * _CELL_HEIGHT + 19,
                        ),
                        text,
                        fontsize=10,
                    )
        document.save(str(path))
    finally:
        document.close()
    return path


def _blank_pdf(path: Path) -> Path:
    """One page with no text and no lines: what a scan without text looks like."""
    document = pymupdf.open()
    try:
        document.new_page(width=595, height=842)
        document.save(str(path))
    finally:
        document.close()
    return path


def _sheet_rows(path: Path) -> dict[str, list[list[object]]]:
    """Every sheet's title mapped to its rows of cell values."""
    workbook = load_workbook(str(path))
    try:
        return {
            sheet.title: [list(row) for row in sheet.iter_rows(values_only=True)]
            for sheet in workbook.worksheets
        }
    finally:
        workbook.close()


# -- Engine --------------------------------------------------------------------


def test_a_ruled_table_becomes_one_sheet(tmp_path: Path) -> None:
    source = _table_pdf(tmp_path / "table.pdf", [TABLE])
    out = _out(tmp_path)

    result = convert_pdf_to_excel(source, out)

    assert result.mode == "tables"
    assert result.table_count == 1
    assert result.sheet_count == 1
    assert result.page_count == 1
    assert result.result_name == "result.xlsx"
    assert result.result_size == (out / "result.xlsx").stat().st_size
    assert [entry.name for entry in out.iterdir()] == ["result.xlsx"]
    assert _sheet_rows(out / "result.xlsx") == {"P1 T1": TABLE}


def test_one_table_per_page_gives_one_sheet_each(tmp_path: Path) -> None:
    second = [["Name", "Score"], ["Ann", "9"], ["Bob", "7"]]
    source = _table_pdf(tmp_path / "two.pdf", [TABLE, second])
    out = _out(tmp_path)

    result = convert_pdf_to_excel(source, out)

    assert result.mode == "tables"
    assert result.page_count == 2
    assert result.table_count == 2
    assert result.sheet_count == 2
    sheets = _sheet_rows(out / "result.xlsx")
    assert list(sheets) == ["P1 T1", "P2 T1"]
    assert sheets["P1 T1"] == TABLE
    assert sheets["P2 T1"] == second


def test_text_starting_with_an_equals_sign_is_stored_as_plain_text(
    tmp_path: Path,
) -> None:
    source = _table_pdf(
        tmp_path / "formulas.pdf", [[["One", "Two", "Three"], FORMULAS]]
    )
    out = _out(tmp_path)

    convert_pdf_to_excel(source, out)

    result_path = out / "result.xlsx"
    workbook = load_workbook(str(result_path))
    try:
        sheet = workbook["P1 T1"]
        cells = [sheet.cell(row=2, column=column) for column in (1, 2, 3)]
        assert [cell.data_type for cell in cells] == ["s", "s", "s"]
        assert [cell.value for cell in cells] == FORMULAS
    finally:
        workbook.close()
    with zipfile.ZipFile(result_path) as archive:
        sheet_parts = [
            name
            for name in archive.namelist()
            if name.startswith("xl/worksheets/sheet") and name.endswith(".xml")
        ]
        assert sheet_parts
        for name in sheet_parts:
            xml = archive.read(name).decode("utf-8")
            assert "<f>" not in xml
            assert "<f " not in xml


def test_a_pdf_without_tables_gets_a_text_sheet(
    pdf_factory: PdfFactory, tmp_path: Path
) -> None:
    source = pdf_factory(tmp_path / "three.pdf", pages=3)
    out = _out(tmp_path)

    result = convert_pdf_to_excel(source, out)

    assert result.mode == "text"
    assert result.table_count == 0
    assert result.sheet_count == 1
    assert result.page_count == 3
    sheets = _sheet_rows(out / "result.xlsx")
    assert list(sheets) == ["Text"]
    rows = sheets["Text"]
    assert rows[0] == ["Page", "Text"]
    assert any("lazy dog" in str(row[1]) for row in rows[1:])
    pages = [row[0] for row in rows[1:]]
    assert all(isinstance(page, int) for page in pages)
    assert set(pages) == {1, 2, 3}


def test_a_pdf_with_no_text_or_tables_has_no_content(tmp_path: Path) -> None:
    source = _blank_pdf(tmp_path / "blank.pdf")
    out = _out(tmp_path)

    with pytest.raises(AppError) as info:
        convert_pdf_to_excel(source, out)

    assert info.value.code == NO_CONTENT
    assert list(out.iterdir()) == []


def test_clean_cell_removes_control_characters_and_trims() -> None:
    assert engine._clean_cell(None) == ""
    assert engine._clean_cell("a\x00b\x1fc") == "abc"
    assert engine._clean_cell("  x  ") == "x"
    assert engine._clean_cell(42) == "42"


def test_is_usable_needs_two_rows_a_wide_row_and_some_text() -> None:
    assert engine._is_usable([["only"]]) is False
    assert engine._is_usable([["a", "b"]]) is False
    assert engine._is_usable([["", ""], ["", ""]]) is False
    assert engine._is_usable([["a", "b"], ["c", "d"]]) is True


def test_sheet_title_is_short_and_free_of_forbidden_characters() -> None:
    table = engine._Table(page=12345678901234567890, index=9999999999, rows=[])

    title = engine._sheet_title(table)

    assert 0 < len(title) <= 31
    assert not any(character in title for character in "[]:*?/\\")


def test_encrypted_pdf_is_rejected(encrypted_pdf: Path, tmp_path: Path) -> None:
    out = _out(tmp_path)

    with pytest.raises(AppError) as info:
        convert_pdf_to_excel(encrypted_pdf, out)

    assert info.value.code == ENCRYPTED
    assert list(out.iterdir()) == []


def test_garbage_behind_a_pdf_header_is_corrupt(tmp_path: Path) -> None:
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"%PDF-1.7\n" + b"garbage " * 200)
    out = _out(tmp_path)

    with pytest.raises(AppError) as info:
        convert_pdf_to_excel(broken, out)

    assert info.value.code == CORRUPT
    assert list(out.iterdir()) == []


def test_too_many_pages_is_rejected_before_reading(
    pdf_factory: PdfFactory, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MAX_PDF_PAGES", "2")
    get_settings.cache_clear()

    def forbidden(path: Path) -> None:
        raise AssertionError("the PDF must not be read")

    monkeypatch.setattr(engine, "_read_pdf", forbidden)
    source = pdf_factory(tmp_path / "three.pdf", pages=3)
    out = _out(tmp_path)

    with pytest.raises(AppError) as info:
        convert_pdf_to_excel(source, out)

    assert info.value.code == TOO_MANY_PAGES
    assert "3" in info.value.message
    assert "2" in info.value.message
    assert list(out.iterdir()) == []


def test_read_failure_is_processing_failed_without_details(
    pdf_factory: PdfFactory, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def explode(path: Path) -> None:
        raise RuntimeError("boom at /secret/path")

    monkeypatch.setattr(engine, "_read_pdf", explode)
    source = pdf_factory(tmp_path / "one.pdf", pages=1)
    out = _out(tmp_path)

    with pytest.raises(AppError) as info:
        convert_pdf_to_excel(source, out)

    assert info.value.code == PROCESSING_FAILED
    assert "secret" not in info.value.message
    assert list(out.iterdir()) == []


def test_output_that_is_not_an_xlsx_is_processing_failed(
    pdf_factory: PdfFactory, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def write_garbage(content: object, destination: Path) -> int:
        destination.write_bytes(b"this is not a zip file")
        return 1

    monkeypatch.setattr(engine, "_write_workbook", write_garbage)
    source = pdf_factory(tmp_path / "one.pdf", pages=1)
    out = _out(tmp_path)

    with pytest.raises(AppError) as info:
        convert_pdf_to_excel(source, out)

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

    def fake(input_path: Path, output_dir: Path) -> PdfToExcelResult:
        with lock:
            state["active"] += 1
            state["entered"] += 1
            state["peak"] = max(state["peak"], state["active"])
        try:
            release.wait(timeout=10)
        finally:
            with lock:
                state["active"] -= 1
        return PdfToExcelResult(1, 0, 1, "text", 1, "result.xlsx")

    monkeypatch.setattr(engine, "_convert_locked", fake)
    threads = [
        threading.Thread(
            target=convert_pdf_to_excel,
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
def post_pdf_to_excel(client: TestClient) -> PostPdfToExcel:
    """post_pdf_to_excel(content, filename="report.pdf")."""

    def _post(
        content: bytes,
        *,
        filename: str = "report.pdf",
        content_type: str = "application/pdf",
    ) -> Response:
        return client.post(
            "/api/pdf-to-excel",
            files={"file": (filename, content, content_type)},
        )

    return _post


def test_success_returns_every_contract_field(
    post_pdf_to_excel: PostPdfToExcel,
    tmp_path: Path,
    storage_dir: Path,
) -> None:
    source = _table_pdf(tmp_path / "table.pdf", [TABLE])

    response = post_pdf_to_excel(source.read_bytes(), filename="Quarterly report.pdf")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == CONTRACT_FIELDS
    assert body["original_name"] == "Quarterly report"
    assert body["mode"] == "tables"
    assert body["table_count"] == 1
    assert body["sheet_count"] == 1
    assert body["page_count"] == 1
    assert body["original_size"] == source.stat().st_size
    assert body["download_name"] == "Quarterly report.xlsx"
    assert body["download_url"] == f"/api/jobs/{body['job_id']}/download"

    output_dir = storage_dir / "outputs" / body["job_id"]
    assert (output_dir / "result.xlsx").stat().st_size == body["result_size"]
    meta = json.loads((output_dir / "meta.json").read_text(encoding="utf-8"))
    assert meta["result_name"] == "result.xlsx"
    assert meta["download_name"] == "Quarterly report.xlsx"
    assert meta["mode"] == "tables"
    assert meta["table_count"] == 1
    assert meta["sheet_count"] == 1
    assert not (storage_dir / "uploads" / body["job_id"]).exists()


def test_a_pdf_without_tables_succeeds_in_text_mode(
    post_pdf_to_excel: PostPdfToExcel,
    pdf_factory: PdfFactory,
    tmp_path: Path,
) -> None:
    source = pdf_factory(tmp_path / "three.pdf", pages=3)

    response = post_pdf_to_excel(source.read_bytes())

    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "text"
    assert body["table_count"] == 0


def test_a_pdf_with_no_content_is_unprocessable_and_leaves_no_files(
    post_pdf_to_excel: PostPdfToExcel,
    tmp_path: Path,
    job_entries: Callable[[], list[str]],
) -> None:
    source = _blank_pdf(tmp_path / "blank.pdf")

    response = post_pdf_to_excel(source.read_bytes())

    assert response.status_code == 422
    assert response.json()["error"]["code"] == NO_CONTENT
    assert job_entries() == []


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
    post_pdf_to_excel: PostPdfToExcel,
    encrypted_pdf: Path,
    job_entries: Callable[[], list[str]],
) -> None:
    contents = {
        "not_pdf": b"this is plain text, not a pdf. " * 20,
        "encrypted": encrypted_pdf.read_bytes(),
        "corrupt": b"%PDF-1.7\n" + b"garbage " * 200,
        "empty": b"",
    }

    response = post_pdf_to_excel(contents[kind])

    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    assert job_entries() == []


def test_too_many_pages_gives_413_and_leaves_no_files(
    post_pdf_to_excel: PostPdfToExcel,
    pdf_factory: PdfFactory,
    tmp_path: Path,
    job_entries: Callable[[], list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MAX_PDF_PAGES", "2")
    get_settings.cache_clear()
    content = pdf_factory(tmp_path / "three.pdf", pages=3).read_bytes()

    response = post_pdf_to_excel(content)

    assert response.status_code == 413
    assert response.json()["error"]["code"] == TOO_MANY_PAGES
    assert job_entries() == []


def test_upload_just_over_the_limit_is_too_large(
    post_pdf_to_excel: PostPdfToExcel,
    job_entries: Callable[[], list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MAX_UPLOAD_MB", "1")
    get_settings.cache_clear()
    content = b"%PDF-" + b"0" * (1024 * 1024 - 4)  # exactly 1 MiB + 1 byte
    assert len(content) == 1024 * 1024 + 1

    response = post_pdf_to_excel(content)

    assert response.status_code == 413
    error = response.json()["error"]
    assert error["code"] == TOO_LARGE
    assert "1 MB" in error["message"]
    assert job_entries() == []


def test_missing_file_field_is_invalid_request(client: TestClient) -> None:
    response = client.post("/api/pdf-to-excel")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == INVALID_REQUEST


def test_engine_failure_returns_processing_failed_without_details(
    post_pdf_to_excel: PostPdfToExcel,
    text_pdf: Path,
    job_entries: Callable[[], list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def explode(path: Path) -> None:
        raise RuntimeError("boom at /secret/path")

    monkeypatch.setattr(engine, "_read_pdf", explode)

    response = post_pdf_to_excel(text_pdf.read_bytes())

    assert response.status_code == 500
    assert response.json()["error"]["code"] == PROCESSING_FAILED
    assert "secret" not in response.text
    assert job_entries() == []


def test_unexpected_error_returns_internal_error_and_cleans_up(
    post_pdf_to_excel: PostPdfToExcel,
    text_pdf: Path,
    job_entries: Callable[[], list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def explode(*args: object, **kwargs: object) -> None:
        raise RuntimeError("boom at /secret/path")

    monkeypatch.setattr(pdf_to_excel_route, "convert_pdf_to_excel", explode)

    response = post_pdf_to_excel(text_pdf.read_bytes())

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert "secret" not in response.text
    assert job_entries() == []


def test_result_downloads_as_an_xlsx_once_and_deletes_the_job(
    client: TestClient,
    post_pdf_to_excel: PostPdfToExcel,
    tmp_path: Path,
    job_entries: Callable[[], list[str]],
) -> None:
    source = _table_pdf(tmp_path / "table.pdf", [TABLE])
    job = post_pdf_to_excel(source.read_bytes(), filename="report.pdf").json()

    response = client.get(str(job["download_url"]))

    assert response.status_code == 200
    assert response.headers["content-type"] == XLSX_TYPE
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["content-disposition"] == (
        'attachment; filename="report.xlsx"'
    )
    assert zipfile.is_zipfile(io.BytesIO(response.content))
    assert len(response.content) == job["result_size"]
    assert job_entries() == []

    second = client.get(str(job["download_url"]))
    assert second.status_code == 404
    assert second.json()["error"]["code"] == JOB_NOT_FOUND
