"""End-to-end checks for Office conversion and PDF text replacement."""

import io
import zipfile
from collections.abc import Callable
from pathlib import Path

import pymupdf
import pytest
from docx import Document
from fastapi.testclient import TestClient
from openpyxl import Workbook
from pptx import Presentation

from app.main import app


def _office_bytes(kind: str) -> bytes:
    buffer = io.BytesIO()
    if kind == "word":
        document = Document()
        document.add_paragraph("Word sample text")
        document.save(buffer)
    elif kind == "powerpoint":
        presentation = Presentation()
        slide = presentation.slides.add_slide(presentation.slide_layouts[6])
        box = slide.shapes.add_textbox(100000, 100000, 6000000, 600000)
        box.text = "PowerPoint sample text"
        presentation.save(buffer)
    else:
        workbook = Workbook()
        workbook.active["A1"] = "Excel sample text"
        workbook.save(buffer)
    return buffer.getvalue()


@pytest.mark.parametrize("kind", ["word", "powerpoint", "excel"])
def test_office_to_pdf_download(
    storage_dir: Path, kind: str
) -> None:
    with TestClient(app) as client:
        response = client.post(
            f"/api/{kind}-to-pdf",
            files={"file": (f"sample.{ {'word': 'docx', 'powerpoint': 'pptx', 'excel': 'xlsx'}[kind]}", _office_bytes(kind))},
        )
        assert response.status_code == 200, response.text
        data = response.json()
        download = client.get(data["download_url"])
        assert download.status_code == 200
        pdf = pymupdf.open(stream=download.content, filetype="pdf")
        try:
            assert pdf.page_count >= 1
            assert "sample text" in " ".join(page.get_text() for page in pdf)
        finally:
            pdf.close()
        assert client.get(data["download_url"]).status_code == 404


def test_invalid_office_package_uses_shared_error(storage_dir: Path) -> None:
    with TestClient(app) as client:
        response = client.post("/api/word-to-pdf", files={"file": ("bad.docx", b"not an Office package")})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "not_office"


def test_wrong_office_type_uses_shared_error(storage_dir: Path) -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/word-to-pdf",
            files={"file": ("wrong.docx", _office_bytes("excel"))},
        )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "not_office"


@pytest.mark.parametrize(
    ("kind", "part"),
    [
        ("word", "word/document.xml"),
        ("powerpoint", "ppt/presentation.xml"),
        ("excel", "xl/workbook.xml"),
    ],
)
def test_malformed_office_xml_is_rejected_and_cleaned(
    storage_dir: Path, kind: str, part: str
) -> None:
    with io.BytesIO() as buffer:
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr(part, "<broken")
        content = buffer.getvalue()
    with TestClient(app) as client:
        response = client.post(
            f"/api/{kind}-to-pdf", files={"file": ("broken.zip", content)}
        )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "not_office"
    files = [str(path.relative_to(storage_dir)) for path in storage_dir.rglob("*") if path.is_file()]
    assert files == []


def test_edit_pdf_replaces_searchable_text(
    storage_dir: Path, pdf_factory: Callable[..., Path], tmp_path: Path
) -> None:
    source = pdf_factory(tmp_path / "source.pdf", pages=1)
    with TestClient(app) as client:
        response = client.post(
            "/api/edit-pdf",
            files={"file": ("source.pdf", source.read_bytes())},
            data={"find": "quick", "replace": "swift"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["replacement_count"] == 18
        download = client.get(response.json()["download_url"])
    pdf = pymupdf.open(stream=download.content, filetype="pdf")
    try:
        text = pdf[0].get_text()
        assert "swift" in text
        assert "quick" not in text
    finally:
        pdf.close()


def test_edit_pdf_reports_no_match(
    storage_dir: Path, pdf_factory: Callable[..., Path], tmp_path: Path
) -> None:
    source = pdf_factory(tmp_path / "source.pdf", pages=1)
    with TestClient(app) as client:
        response = client.post(
            "/api/edit-pdf",
            files={"file": ("source.pdf", source.read_bytes())},
            data={"find": "absent phrase", "replace": "new phrase"},
        )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "no_match"
