"""Tests for the PDF to PowerPoint engine and POST /api/pdf-to-pptx."""

import io
import json
import threading
import time
import zipfile
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pymupdf
import pytest
from app.api.routes import pdf_to_pptx as pdf_to_pptx_route
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
from app.services import pdf_to_pptx as engine
from app.services.pdf_to_pptx import PdfToPptxResult, convert_pdf_to_pptx
from fastapi.testclient import TestClient
from httpx import Response
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE_TYPE
from pptx.presentation import Presentation as PresentationObject
from pptx.shapes.base import BaseShape
from pptx.slide import Slide

PdfFactory = Callable[..., Path]
PostPdfToPptx = Callable[..., Response]

PPTX_TYPE = (
    "application/vnd.openxmlformats-officedocument.presentationml.presentation"
)
CONTRACT_FIELDS = {
    "job_id",
    "original_name",
    "page_count",
    "slide_count",
    "mode",
    "original_size",
    "result_size",
    "download_name",
    "download_url",
}

# A 595 x 842 point page is this many EMU (1 point = 12700 EMU).
A4_WIDTH_EMU = 7_556_500
A4_HEIGHT_EMU = 10_693_400


@pytest.fixture(autouse=True)
def _reset_pdf_to_pptx_gate() -> Iterator[None]:
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


def _pdf(
    path: Path,
    sizes: list[tuple[float, float]],
    *,
    text: str = "Hello",
    color: tuple[float, float, float] = (0, 0, 0),
    fontname: str = "helv",
    rotate: int | None = None,
) -> Path:
    """One page per size, each with `text` drawn at (72, 100) in 12 points.

    Rotation is set after the text is drawn, so the page content stays the same
    and only its orientation changes.
    """
    document = pymupdf.open()
    try:
        for width, height in sizes:
            page = document.new_page(width=width, height=height)
            page.insert_text(
                (72, 100), text, fontsize=12, fontname=fontname, color=color
            )
            if rotate is not None:
                page.set_rotation(rotate)
        document.save(str(path))
    finally:
        document.close()
    return path


def _blank_pdf(path: Path) -> Path:
    """One page with nothing drawn on it."""
    document = pymupdf.open()
    try:
        document.new_page(width=595, height=842)
        document.save(str(path))
    finally:
        document.close()
    return path


def _open(path: Path) -> PresentationObject:
    return Presentation(str(path))


def _text_of(slide: Slide) -> str:
    """The text of every shape that has a text frame, one shape per line."""
    return "\n".join(
        shape.text_frame.text for shape in slide.shapes if shape.has_text_frame
    )


def _pictures(slide: Slide) -> list[BaseShape]:
    return [
        shape
        for shape in slide.shapes
        if shape.shape_type == MSO_SHAPE_TYPE.PICTURE
    ]


def _runs(slide: Slide) -> list[Any]:
    """Every text run on the slide, in order."""
    runs: list[Any] = []
    for shape in slide.shapes:
        if shape.has_text_frame:
            for paragraph in shape.text_frame.paragraphs:
                runs.extend(paragraph.runs)
    return runs


def _paragraph_count(slide: Slide) -> int:
    return sum(
        len(shape.text_frame.paragraphs)
        for shape in slide.shapes
        if shape.has_text_frame
    )


def _run_with(slide: Slide, text: str) -> Any:
    """The first run whose text is exactly `text`."""
    for run in _runs(slide):
        if run.text == text:
            return run
    raise AssertionError(f"no run with the text {text!r}")


# -- Engine: pictures and editable modes ---------------------------------------


def test_pictures_mode_gives_one_picture_per_slide(
    pdf_factory: PdfFactory, tmp_path: Path
) -> None:
    source = pdf_factory(tmp_path / "three.pdf", pages=3)
    out = _out(tmp_path)

    result = convert_pdf_to_pptx(source, out, "pictures")

    assert result.mode == "pictures"
    assert result.page_count == 3
    assert result.slide_count == 3
    assert result.result_name == "result.pptx"
    assert result.result_size == (out / "result.pptx").stat().st_size
    assert [entry.name for entry in out.iterdir()] == ["result.pptx"]
    presentation = _open(out / "result.pptx")
    assert len(presentation.slides) == 3
    for slide in presentation.slides:
        assert len(slide.shapes) == 1
        assert len(_pictures(slide)) == 1


def test_editable_mode_rebuilds_text_as_arial_runs_of_the_same_size(
    pdf_factory: PdfFactory, tmp_path: Path
) -> None:
    source = pdf_factory(tmp_path / "two.pdf", pages=2)
    out = _out(tmp_path)

    result = convert_pdf_to_pptx(source, out, "editable")

    assert result.mode == "editable"
    assert result.slide_count == 2
    presentation = _open(out / "result.pptx")
    assert presentation.slide_width == A4_WIDTH_EMU
    assert presentation.slide_height == A4_HEIGHT_EMU
    first = presentation.slides[0]
    assert "lazy dog" in _text_of(first)
    assert _paragraph_count(first) == 18
    runs = _runs(first)
    assert runs
    for run in runs:
        assert run.font.name == "Arial"
        assert run.font.size is not None
        assert abs(run.font.size.pt - 11) <= 0.1


def test_editable_mode_keeps_the_text_colour(tmp_path: Path) -> None:
    source = _pdf(tmp_path / "red.pdf", [(595, 842)], color=(1, 0, 0))
    out = _out(tmp_path)

    convert_pdf_to_pptx(source, out, "editable")

    slide = _open(out / "result.pptx").slides[0]
    assert _run_with(slide, "Hello").font.color.rgb == RGBColor(255, 0, 0)


def test_editable_mode_keeps_bold(tmp_path: Path) -> None:
    source = _pdf(tmp_path / "bold.pdf", [(595, 842)], fontname="hebo")
    out = _out(tmp_path)

    convert_pdf_to_pptx(source, out, "editable")

    slide = _open(out / "result.pptx").slides[0]
    assert _run_with(slide, "Hello").font.bold is True


def test_editable_mode_keeps_images_and_text(image_pdf: Path, tmp_path: Path) -> None:
    out = _out(tmp_path)

    result = convert_pdf_to_pptx(image_pdf, out, "editable")

    assert result.slide_count == 4
    presentation = _open(out / "result.pptx")
    assert len(presentation.slides) == 4
    for slide in presentation.slides:
        assert len(_pictures(slide)) >= 1
        assert "lazy dog" in _text_of(slide)


def test_a_rotated_page_falls_back_to_a_picture_in_editable_mode(
    tmp_path: Path,
) -> None:
    source = _pdf(tmp_path / "rotated.pdf", [(595, 842)], rotate=90)
    out = _out(tmp_path)

    result = convert_pdf_to_pptx(source, out, "editable")

    assert result.slide_count == 1
    slide = _open(out / "result.pptx").slides[0]
    assert len(slide.shapes) == 1
    assert len(_pictures(slide)) == 1


def test_mixed_page_sizes_are_fitted_and_centred_on_the_first_pages_slide(
    tmp_path: Path,
) -> None:
    source = _pdf(tmp_path / "mixed.pdf", [(595, 842), (842, 595)])
    out = _out(tmp_path)

    convert_pdf_to_pptx(source, out, "pictures")

    presentation = _open(out / "result.pptx")
    assert presentation.slide_width == A4_WIDTH_EMU
    assert presentation.slide_height == A4_HEIGHT_EMU
    pictures = _pictures(presentation.slides[1])
    assert len(pictures) == 1
    picture = pictures[0]
    assert abs(picture.width - A4_WIDTH_EMU) <= 2000
    assert abs(picture.left - 0) <= 2000
    assert picture.top > 0


def test_a_blank_page_is_an_empty_slide_in_editable_mode_and_a_picture_in_pictures_mode(
    tmp_path: Path,
) -> None:
    source = _blank_pdf(tmp_path / "blank.pdf")
    editable_out = _out(tmp_path / "editable")
    pictures_out = _out(tmp_path / "pictures")

    convert_pdf_to_pptx(source, editable_out, "editable")
    convert_pdf_to_pptx(source, pictures_out, "pictures")

    editable = _open(editable_out / "result.pptx")
    assert len(editable.slides) == 1
    assert len(editable.slides[0].shapes) == 0
    pictures = _open(pictures_out / "result.pptx")
    assert len(pictures.slides) == 1
    assert len(pictures.slides[0].shapes) == 1
    assert len(_pictures(pictures.slides[0])) == 1


def test_an_oversized_page_is_rendered_at_a_lower_dpi_instead_of_failing(
    pdf_factory: PdfFactory, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MAX_RENDER_PIXELS", "200000")
    get_settings.cache_clear()
    source = pdf_factory(tmp_path / "one.pdf", pages=1)
    out = _out(tmp_path)

    convert_pdf_to_pptx(source, out, "pictures")

    picture = _pictures(_open(out / "result.pptx").slides[0])[0]
    width, height = picture.image.size
    assert 0 < width * height <= 200_000


# -- Helpers under test --------------------------------------------------------


def test_slide_size_follows_the_first_page_within_powerpoints_limits() -> None:
    assert engine._slide_size(595, 842) == (A4_WIDTH_EMU, A4_HEIGHT_EMU)
    assert engine._slide_size(10, 10) == (914_400, 914_400)
    assert engine._slide_size(10000, 5000) == (50_800_000, 25_400_000)
    assert engine._slide_size(10000, 20) == (50_800_000, 914_400)


@pytest.mark.parametrize(
    "size",
    [(0, 100), (100, 0), (float("nan"), 100), (-5, 10)],
    ids=["zero-width", "zero-height", "nan-width", "negative-width"],
)
def test_slide_size_rejects_unusable_sizes(size: tuple[float, float]) -> None:
    with pytest.raises(ValueError, match="usable size"):
        engine._slide_size(*size)


def test_placement_scales_to_fit_and_centres() -> None:
    portrait = engine._placement(595, 842, A4_WIDTH_EMU, A4_HEIGHT_EMU)
    assert portrait.scale == pytest.approx(1.0)
    assert portrait.left == pytest.approx(0.0, abs=1e-6)
    assert portrait.top == pytest.approx(0.0, abs=1e-6)

    landscape = engine._placement(842, 595, A4_WIDTH_EMU, A4_HEIGHT_EMU)
    assert landscape.scale == pytest.approx(595 / 842)
    assert landscape.left == pytest.approx(0.0, abs=1e-6)
    assert landscape.top > 0


def test_fit_dpi_is_150_unless_the_budget_is_small() -> None:
    assert engine._fit_dpi(595, 842, 30_000_000) == 150

    lowered = engine._fit_dpi(595, 842, 200_000)

    assert lowered < 150
    assert engine._fits(595, 842, lowered, 200_000) is True


def test_fit_dpi_rejects_a_page_with_no_size_or_an_impossible_budget() -> None:
    with pytest.raises(ValueError, match="usable size"):
        engine._fit_dpi(0, 10, 30_000_000)
    with pytest.raises(ValueError, match="too large"):
        engine._fit_dpi(595, 842, 1)


def test_clean_text_removes_what_xml_cannot_hold_and_flattens_lines() -> None:
    assert engine._clean_text("a\x00b\x1fc") == "abc"
    flattened = engine._clean_text("one\r\ntwo")
    assert "\r" not in flattened
    assert "\n" not in flattened
    assert engine._clean_text("a\ud800b") == "ab"


def test_font_size_is_clamped_and_falls_back_for_bad_values() -> None:
    assert engine._font_size(12, 1.0) == 12.0
    assert engine._font_size(0.1, 1.0) == 1.0
    assert engine._font_size(1e9, 1.0) == 4000.0
    assert engine._font_size("bad", 1.0) == 12.0
    assert engine._font_size(float("nan"), 1.0) == 12.0


def test_check_pptx_accepts_only_a_package_with_the_right_slide_count(
    tmp_path: Path,
) -> None:
    presentation = Presentation()
    for _ in range(2):
        presentation.slides.add_slide(presentation.slide_layouts[6])
    valid = tmp_path / "two.pptx"
    presentation.save(str(valid))
    empty = tmp_path / "empty.pptx"
    empty.write_bytes(b"")
    junk = tmp_path / "junk.pptx"
    junk.write_bytes(b"this is not a zip file")

    engine._check_pptx(valid, 2)
    with pytest.raises(ValueError, match="wrong number of slides"):
        engine._check_pptx(valid, 3)
    with pytest.raises(ValueError, match="not written"):
        engine._check_pptx(tmp_path / "missing.pptx", 1)
    with pytest.raises(ValueError, match="not written"):
        engine._check_pptx(empty, 1)
    with pytest.raises(ValueError, match="not a zip"):
        engine._check_pptx(junk, 1)


def test_parse_mode_accepts_only_pictures_and_editable() -> None:
    for mode in ("pictures", "editable"):
        assert engine.parse_mode(mode) == mode
    for bad in ("Pictures", "", None, 1, "both"):
        with pytest.raises(AppError) as info:
            engine.parse_mode(bad)
        assert info.value.code == INVALID_REQUEST
        assert "pictures" in info.value.message
        assert "editable" in info.value.message


# -- Engine: failures ----------------------------------------------------------


def test_an_invalid_mode_never_reaches_the_engine(
    pdf_factory: PdfFactory, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(input_path: Path, output_dir: Path, mode: str) -> None:
        raise AssertionError("the engine must not run")

    monkeypatch.setattr(engine, "_convert_locked", forbidden)
    source = pdf_factory(tmp_path / "one.pdf", pages=1)
    out = _out(tmp_path)

    with pytest.raises(AppError) as info:
        convert_pdf_to_pptx(source, out, "bogus")

    assert info.value.code == INVALID_REQUEST
    assert list(out.iterdir()) == []


def test_encrypted_pdf_is_rejected(encrypted_pdf: Path, tmp_path: Path) -> None:
    out = _out(tmp_path)

    with pytest.raises(AppError) as info:
        convert_pdf_to_pptx(encrypted_pdf, out, "pictures")

    assert info.value.code == ENCRYPTED
    assert list(out.iterdir()) == []


def test_garbage_behind_a_pdf_header_is_corrupt(tmp_path: Path) -> None:
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"%PDF-1.7\n" + b"garbage " * 200)
    out = _out(tmp_path)

    with pytest.raises(AppError) as info:
        convert_pdf_to_pptx(broken, out, "pictures")

    assert info.value.code == CORRUPT
    assert list(out.iterdir()) == []


def test_too_many_pages_is_rejected_before_building(
    pdf_factory: PdfFactory, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MAX_PDF_PAGES", "2")
    get_settings.cache_clear()

    def forbidden(document: object, mode: str, destination: Path) -> int:
        raise AssertionError("the presentation must not be built")

    monkeypatch.setattr(engine, "_build_presentation", forbidden)
    source = pdf_factory(tmp_path / "three.pdf", pages=3)
    out = _out(tmp_path)

    with pytest.raises(AppError) as info:
        convert_pdf_to_pptx(source, out, "pictures")

    assert info.value.code == TOO_MANY_PAGES
    assert "3" in info.value.message
    assert "2" in info.value.message
    assert list(out.iterdir()) == []


def test_build_failure_is_processing_failed_without_details(
    pdf_factory: PdfFactory, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def explode(document: object, mode: str, destination: Path) -> int:
        raise RuntimeError("boom at /secret/path")

    monkeypatch.setattr(engine, "_build_presentation", explode)
    source = pdf_factory(tmp_path / "one.pdf", pages=1)
    out = _out(tmp_path)

    with pytest.raises(AppError) as info:
        convert_pdf_to_pptx(source, out, "pictures")

    assert info.value.code == PROCESSING_FAILED
    assert "secret" not in info.value.message
    assert list(out.iterdir()) == []


def test_output_that_is_not_a_pptx_is_processing_failed(
    pdf_factory: PdfFactory, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def write_garbage(document: object, mode: str, destination: Path) -> int:
        destination.write_bytes(b"this is not a zip file")
        return 1

    monkeypatch.setattr(engine, "_build_presentation", write_garbage)
    source = pdf_factory(tmp_path / "one.pdf", pages=1)
    out = _out(tmp_path)

    with pytest.raises(AppError) as info:
        convert_pdf_to_pptx(source, out, "pictures")

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

    def fake(input_path: Path, output_dir: Path, mode: str) -> PdfToPptxResult:
        with lock:
            state["active"] += 1
            state["entered"] += 1
            state["peak"] = max(state["peak"], state["active"])
        try:
            release.wait(timeout=10)
        finally:
            with lock:
                state["active"] -= 1
        return PdfToPptxResult(1, 1, "pictures", 1, "result.pptx")

    monkeypatch.setattr(engine, "_convert_locked", fake)
    threads = [
        threading.Thread(
            target=convert_pdf_to_pptx,
            args=(tmp_path / "in.pdf", tmp_path / "out", "pictures"),
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


@pytest.fixture
def post_pdf_to_pptx(client: TestClient) -> PostPdfToPptx:
    """post_pdf_to_pptx(content, mode="pictures", filename="report.pdf").

    A mode of None leaves the field out of the form altogether.
    """

    def _post(
        content: bytes,
        *,
        mode: str | None = "pictures",
        filename: str = "report.pdf",
        content_type: str = "application/pdf",
    ) -> Response:
        data = {} if mode is None else {"mode": mode}
        return client.post(
            "/api/pdf-to-pptx",
            files={"file": (filename, content, content_type)},
            data=data,
        )

    return _post


def test_success_in_pictures_mode_returns_every_contract_field(
    post_pdf_to_pptx: PostPdfToPptx,
    pdf_factory: PdfFactory,
    tmp_path: Path,
    storage_dir: Path,
) -> None:
    source = pdf_factory(tmp_path / "three.pdf", pages=3)

    response = post_pdf_to_pptx(
        source.read_bytes(), mode="pictures", filename="Quarterly report.pdf"
    )

    assert response.status_code == 200
    body = response.json()
    assert set(body) == CONTRACT_FIELDS
    assert body["original_name"] == "Quarterly report"
    assert body["mode"] == "pictures"
    assert body["page_count"] == 3
    assert body["slide_count"] == 3
    assert body["original_size"] == source.stat().st_size
    assert body["download_name"] == "Quarterly report.pptx"
    assert body["download_url"] == f"/api/jobs/{body['job_id']}/download"

    output_dir = storage_dir / "outputs" / body["job_id"]
    assert (output_dir / "result.pptx").stat().st_size == body["result_size"]
    meta = json.loads((output_dir / "meta.json").read_text(encoding="utf-8"))
    assert meta["result_name"] == "result.pptx"
    assert meta["download_name"] == "Quarterly report.pptx"
    assert meta["mode"] == "pictures"
    assert meta["page_count"] == 3
    assert meta["slide_count"] == 3
    assert not (storage_dir / "uploads" / body["job_id"]).exists()


def test_success_in_editable_mode_reports_editable(
    post_pdf_to_pptx: PostPdfToPptx,
    pdf_factory: PdfFactory,
    tmp_path: Path,
) -> None:
    source = pdf_factory(tmp_path / "two.pdf", pages=2)

    response = post_pdf_to_pptx(source.read_bytes(), mode="editable")

    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "editable"
    assert body["slide_count"] == 2


@pytest.mark.parametrize("mode", ["bogus", "Pictures", "", None])
def test_an_invalid_or_missing_mode_is_rejected_before_anything_is_created(
    post_pdf_to_pptx: PostPdfToPptx,
    text_pdf: Path,
    job_entries: Callable[[], list[str]],
    mode: str | None,
) -> None:
    response = post_pdf_to_pptx(text_pdf.read_bytes(), mode=mode)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == INVALID_REQUEST
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
    post_pdf_to_pptx: PostPdfToPptx,
    encrypted_pdf: Path,
    job_entries: Callable[[], list[str]],
) -> None:
    contents = {
        "not_pdf": b"this is plain text, not a pdf. " * 20,
        "encrypted": encrypted_pdf.read_bytes(),
        "corrupt": b"%PDF-1.7\n" + b"garbage " * 200,
        "empty": b"",
    }

    response = post_pdf_to_pptx(contents[kind])

    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    assert job_entries() == []


def test_too_many_pages_gives_413_and_leaves_no_files(
    post_pdf_to_pptx: PostPdfToPptx,
    pdf_factory: PdfFactory,
    tmp_path: Path,
    job_entries: Callable[[], list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MAX_PDF_PAGES", "2")
    get_settings.cache_clear()
    content = pdf_factory(tmp_path / "three.pdf", pages=3).read_bytes()

    response = post_pdf_to_pptx(content)

    assert response.status_code == 413
    assert response.json()["error"]["code"] == TOO_MANY_PAGES
    assert job_entries() == []


def test_upload_just_over_the_limit_is_too_large(
    post_pdf_to_pptx: PostPdfToPptx,
    job_entries: Callable[[], list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MAX_UPLOAD_MB", "1")
    get_settings.cache_clear()
    content = b"%PDF-" + b"0" * (1024 * 1024 - 4)  # exactly 1 MiB + 1 byte
    assert len(content) == 1024 * 1024 + 1

    response = post_pdf_to_pptx(content)

    assert response.status_code == 413
    error = response.json()["error"]
    assert error["code"] == TOO_LARGE
    assert "1 MB" in error["message"]
    assert job_entries() == []


def test_missing_file_field_is_invalid_request(client: TestClient) -> None:
    response = client.post("/api/pdf-to-pptx", data={"mode": "pictures"})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == INVALID_REQUEST


def test_engine_failure_returns_processing_failed_without_details(
    post_pdf_to_pptx: PostPdfToPptx,
    text_pdf: Path,
    job_entries: Callable[[], list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def explode(document: object, mode: str, destination: Path) -> int:
        raise RuntimeError("boom at /secret/path")

    monkeypatch.setattr(engine, "_build_presentation", explode)

    response = post_pdf_to_pptx(text_pdf.read_bytes())

    assert response.status_code == 500
    assert response.json()["error"]["code"] == PROCESSING_FAILED
    assert "secret" not in response.text
    assert job_entries() == []


def test_unexpected_error_returns_internal_error_and_cleans_up(
    post_pdf_to_pptx: PostPdfToPptx,
    text_pdf: Path,
    job_entries: Callable[[], list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def explode(*args: object, **kwargs: object) -> None:
        raise RuntimeError("boom at /secret/path")

    monkeypatch.setattr(pdf_to_pptx_route, "convert_pdf_to_pptx", explode)

    response = post_pdf_to_pptx(text_pdf.read_bytes())

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert "secret" not in response.text
    assert job_entries() == []


def test_result_downloads_as_a_pptx_once_and_deletes_the_job(
    client: TestClient,
    post_pdf_to_pptx: PostPdfToPptx,
    pdf_factory: PdfFactory,
    tmp_path: Path,
    job_entries: Callable[[], list[str]],
) -> None:
    source = pdf_factory(tmp_path / "one.pdf", pages=1)
    job = post_pdf_to_pptx(source.read_bytes(), filename="report.pdf").json()

    response = client.get(str(job["download_url"]))

    assert response.status_code == 200
    assert response.headers["content-type"] == PPTX_TYPE
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["content-disposition"] == (
        'attachment; filename="report.pptx"'
    )
    assert zipfile.is_zipfile(io.BytesIO(response.content))
    assert len(response.content) == job["result_size"]
    assert job_entries() == []

    second = client.get(str(job["download_url"]))
    assert second.status_code == 404
    assert second.json()["error"]["code"] == JOB_NOT_FOUND