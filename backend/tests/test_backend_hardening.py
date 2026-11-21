"""Regression checks for shared execution and hostile PDF inputs."""

import io
import threading
from pathlib import Path

import pikepdf
import pymupdf
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from pptx import Presentation

from app.core.config import get_settings
from app.services import compress, pdf_to_jpg
from app.services.pdf_common import GLOBAL_GATE

PDF_ROUTES = (
    "/api/compress",
    "/api/pdf-to-jpg",
    "/api/pdf-to-word",
    "/api/pdf-to-excel",
    "/api/pdf-to-pptx",
    "/api/merge",
    "/api/split",
    "/api/edit-pdf",
)


def _post_pdf(client: TestClient, route: str, content: bytes):
    if route == "/api/merge":
        return client.post(
            route,
            files=[("files", ("a.pdf", content)), ("files", ("b.pdf", content))],
        )
    data = {
        "/api/compress": {"level": "light"},
        "/api/pdf-to-jpg": {"quality": "low"},
        "/api/pdf-to-pptx": {"mode": "pictures"},
        "/api/split": {"ranges": "1", "mode": "extract"},
        "/api/edit-pdf": {"find": "hello", "replace": "world"},
    }.get(route, {})
    return client.post(route, files={"file": ("a.pdf", content)}, data=data)


@pytest.mark.parametrize("route", PDF_ROUTES)
def test_encrypted_pdf_is_rejected_by_every_pdf_route(
    client: TestClient, encrypted_pdf: Path, route: str
) -> None:
    response = _post_pdf(client, route, encrypted_pdf.read_bytes())
    assert response.status_code == 400, response.text
    assert response.json()["error"]["code"] == "encrypted"


@pytest.mark.parametrize("route", PDF_ROUTES)
def test_corrupt_pdf_is_rejected_by_every_pdf_route(
    client: TestClient, route: str
) -> None:
    response = _post_pdf(client, route, b"%PDF-1.7\nnot a document")
    assert response.status_code == 400, response.text
    assert response.json()["error"]["code"] == "corrupt"


@pytest.mark.parametrize("route", PDF_ROUTES)
def test_zero_page_pdf_is_rejected_by_every_pdf_route(
    client: TestClient, tmp_path: Path, route: str
) -> None:
    path = tmp_path / "empty.pdf"
    pikepdf.Pdf.new().save(path)
    response = _post_pdf(client, route, path.read_bytes())
    assert response.status_code == 400, response.text
    assert response.json()["error"]["code"] == "corrupt"


def _scan_pdf(path: Path) -> bytes:
    image = Image.new("RGB", (100, 100), "white")
    with io.BytesIO() as buffer:
        image.save(buffer, format="PNG")
        pixels = buffer.getvalue()
    image.close()
    document = pymupdf.open()
    try:
        page = document.new_page()
        page.insert_image(pymupdf.Rect(50, 50, 150, 150), stream=pixels)
        document.save(path)
    finally:
        document.close()
    return path.read_bytes()


@pytest.mark.parametrize(
    ("route", "expected"),
    [("/api/pdf-to-excel", "no_content"), ("/api/edit-pdf", "no_text")],
)
def test_scanned_pdf_has_a_helpful_error(
    client: TestClient, tmp_path: Path, route: str, expected: str
) -> None:
    response = _post_pdf(client, route, _scan_pdf(tmp_path / "scan.pdf"))
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == expected


@pytest.mark.parametrize("route", ["/api/pdf-to-jpg", "/api/pdf-to-pptx"])
def test_oversized_page_is_rejected_before_rendering(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, route: str
) -> None:
    monkeypatch.setenv("MAX_RENDER_PIXELS", "1000")
    get_settings.cache_clear()
    path = tmp_path / "poster.pdf"
    document = pymupdf.open()
    try:
        document.new_page(width=14_400, height=14_400)
        document.save(path)
    finally:
        document.close()
    response = _post_pdf(client, route, path.read_bytes())
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "page_too_large"


def test_cross_endpoint_gate_stays_locked_during_rebuild(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first_entered = threading.Event()
    second_entered = threading.Event()
    release = threading.Event()

    def fake_compress(_source: Path, _target: Path, _level: str):
        first_entered.set()
        release.wait(timeout=5)
        return compress.CompressionResult(1, 1, True, 1)

    def fake_jpg(_source: Path, _target: Path, _quality: str):
        second_entered.set()
        return pdf_to_jpg.PdfToJpgResult(1, 1, 1, "jpg", "result.jpg")

    monkeypatch.setattr(compress, "_compress_locked", fake_compress)
    monkeypatch.setattr(pdf_to_jpg, "_convert_locked", fake_jpg)
    first = threading.Thread(
        target=compress.compress_pdf,
        args=(tmp_path / "a.pdf", tmp_path / "out.pdf", "light"),
    )
    second = threading.Thread(
        target=pdf_to_jpg.convert_pdf_to_jpg,
        args=(tmp_path / "b.pdf", tmp_path / "out", "low"),
    )
    try:
        first.start()
        assert first_entered.wait(timeout=2)
        second.start()
        assert not second_entered.wait(timeout=0.2)
        GLOBAL_GATE.rebuild()
        assert not second_entered.wait(timeout=0.2)
    finally:
        release.set()
        first.join(timeout=5)
        if second.ident is not None:
            second.join(timeout=5)
    assert second_entered.is_set()


def test_split_repeated_ranges_respect_output_page_limit(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MAX_PDF_PAGES", "1")
    get_settings.cache_clear()
    path = tmp_path / "one.pdf"
    document = pymupdf.open()
    try:
        document.new_page()
        document.save(path)
    finally:
        document.close()
    response = client.post(
        "/api/split",
        files={"file": ("one.pdf", path.read_bytes())},
        data={"ranges": "1,1", "mode": "extract"},
    )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "too_many_pages"


def test_edit_checks_page_limit_before_search(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MAX_PDF_PAGES", "1")
    get_settings.cache_clear()
    path = tmp_path / "two.pdf"
    document = pymupdf.open()
    try:
        document.new_page()
        document.new_page()
        document.save(path)
    finally:
        document.close()
    response = _post_pdf(client, "/api/edit-pdf", path.read_bytes())
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "too_many_pages"


def test_office_conversion_checks_slide_count_before_rendering(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MAX_PDF_PAGES", "1")
    get_settings.cache_clear()
    presentation = Presentation()
    for _ in range(2):
        presentation.slides.add_slide(presentation.slide_layouts[6])
    with io.BytesIO() as buffer:
        presentation.save(buffer)
        content = buffer.getvalue()
    response = client.post(
        "/api/powerpoint-to-pdf",
        files={"file": ("two.pptx", content)},
    )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "too_many_pages"
