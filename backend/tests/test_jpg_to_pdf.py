"""Tests for the JPG/PNG to PDF engine and POST /api/jpg-to-pdf."""

import io
import json
import os
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import pymupdf
import pytest
from fastapi.testclient import TestClient
from httpx import Response
from PIL import Image, ImageOps

from app.api.routes import jpg_to_pdf as jpg_to_pdf_route
from app.core.config import get_settings
from app.core.errors import (
    INVALID_PAGE_SIZE,
    INVALID_REQUEST,
    NOT_IMAGE,
    PROCESSING_FAILED,
    TOO_LARGE,
    TOO_MANY_FILES,
    AppError,
)
from app.services import jpg_to_pdf as engine
from app.services.jpg_to_pdf import (
    JpgToPdfResult,
    convert_images_to_pdf,
    parse_page_size,
)

PostJpgToPdf = Callable[..., Response]

CONTRACT_FIELDS = {
    "job_id",
    "page_count",
    "total_input_size",
    "result_size",
    "page_size",
    "download_name",
    "download_url",
}


@pytest.fixture(autouse=True)
def _reset_jpg_to_pdf_gate() -> Iterator[None]:
    """Rebuild this engine's gate after every test in this module."""
    yield
    get_settings.cache_clear()
    engine.rebuild_concurrency_gate()


# -- Builders ------------------------------------------------------------------


def _photo(width: int, height: int) -> Image.Image:
    """A smooth, photo-like RGB image."""
    vertical = Image.linear_gradient("L").resize(
        (width, height), Image.Resampling.BILINEAR
    )
    sideways = vertical.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    return Image.merge("RGB", (vertical, sideways, ImageOps.invert(vertical)))


def _jpeg(
    width: int = 200,
    height: int = 120,
    *,
    mode: str = "RGB",
    orientation: int | None = None,
) -> bytes:
    """A JPEG at 72 DPI, so one pixel is one point in "fit" mode."""
    image = _photo(width, height)
    if mode != "RGB":
        image = image.convert(mode)
    buffer = io.BytesIO()
    if orientation is None:
        image.save(buffer, format="JPEG", quality=90, dpi=(72, 72))
    else:
        exif = Image.Exif()
        exif[0x0112] = orientation
        image.save(buffer, format="JPEG", quality=90, dpi=(72, 72), exif=exif)
    return buffer.getvalue()


def _png(width: int = 200, height: int = 120, *, mode: str = "RGB") -> bytes:
    image = _photo(width, height)
    if mode != "RGB":
        image = image.convert(mode)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", dpi=(72, 72))
    return buffer.getvalue()


def _write_images(tmp_path: Path, contents: list[bytes]) -> list[Path]:
    folder = tmp_path / "in"
    folder.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for number, content in enumerate(contents, start=1):
        path = folder / f"{number:03d}.bin"
        path.write_bytes(content)
        paths.append(path)
    return paths


def _out(tmp_path: Path) -> Path:
    folder = tmp_path / "out"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _page_sizes(pdf: Path) -> list[tuple[int, int]]:
    with pymupdf.open(str(pdf)) as document:
        return [(round(page.rect.width), round(page.rect.height)) for page in document]


def _wait_until(predicate: Callable[[], bool], timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


# -- Engine --------------------------------------------------------------------


def test_fit_pages_match_the_image_sizes_in_order(tmp_path: Path) -> None:
    sources = _write_images(
        tmp_path, [_jpeg(300, 200), _png(100, 150), _jpeg(80, 80)]
    )
    out = _out(tmp_path)

    result = convert_images_to_pdf(sources, out, "fit")

    assert result.page_count == 3
    assert _page_sizes(out / "result.pdf") == [(300, 200), (100, 150), (80, 80)]


def test_a4_pages_are_a4_and_follow_the_image_orientation(tmp_path: Path) -> None:
    sources = _write_images(tmp_path, [_jpeg(100, 200), _jpeg(200, 100)])
    out = _out(tmp_path)

    convert_images_to_pdf(sources, out, "a4")

    assert _page_sizes(out / "result.pdf") == [(595, 842), (842, 595)]


def test_a4_image_stays_inside_the_margins(tmp_path: Path) -> None:
    sources = _write_images(tmp_path, [_jpeg(400, 300)])
    out = _out(tmp_path)

    convert_images_to_pdf(sources, out, "a4")

    with pymupdf.open(str(out / "result.pdf")) as document:
        page = document[0]
        xref = page.get_images(full=True)[0][0]
        rect = page.get_image_rects(xref)[0]
        page_rect = page.rect
    assert rect.x0 >= 27
    assert rect.y0 >= 27
    assert rect.x1 <= page_rect.width - 27
    assert rect.y1 <= page_rect.height - 27


def test_png_transparency_is_flattened_so_the_pdf_has_no_soft_mask(
    tmp_path: Path,
) -> None:
    buffer = io.BytesIO()
    Image.new("RGBA", (120, 80), (255, 0, 0, 0)).save(
        buffer, format="PNG", dpi=(72, 72)
    )
    sources = _write_images(tmp_path, [buffer.getvalue()])
    out = _out(tmp_path)

    convert_images_to_pdf(sources, out, "fit")

    with pymupdf.open(str(out / "result.pdf")) as document:
        images = document[0].get_images(full=True)
    assert len(images) == 1
    assert images[0][1] == 0  # no soft mask


UNUSUAL_IMAGES: dict[str, Callable[[], bytes]] = {
    "cmyk_jpeg": lambda: _jpeg(mode="CMYK"),
    "gray_jpeg": lambda: _jpeg(mode="L"),
    "palette_png": lambda: _png(mode="P"),
    "gray_png": lambda: _png(mode="L"),
    "rgba_png": lambda: _png(mode="RGBA"),
}


@pytest.mark.parametrize("name", list(UNUSUAL_IMAGES))
def test_unusual_image_modes_are_accepted(name: str, tmp_path: Path) -> None:
    sources = _write_images(tmp_path, [UNUSUAL_IMAGES[name]()])
    out = _out(tmp_path)

    result = convert_images_to_pdf(sources, out, "fit")

    assert result.page_count == 1
    with pymupdf.open(str(out / "result.pdf")) as document:
        pixmap = document[0].get_pixmap(dpi=36)
        assert pixmap.width > 0


def test_exif_rotated_jpeg_is_turned_upright(tmp_path: Path) -> None:
    sources = _write_images(tmp_path, [_jpeg(300, 200, orientation=6)])
    out = _out(tmp_path)

    convert_images_to_pdf(sources, out, "fit")

    assert _page_sizes(out / "result.pdf") == [(200, 300)]


def test_text_file_is_not_image(tmp_path: Path) -> None:
    sources = _write_images(tmp_path, [b"just some plain text. " * 20])
    out = _out(tmp_path)

    with pytest.raises(AppError) as info:
        convert_images_to_pdf(sources, out, "fit")

    assert info.value.code == NOT_IMAGE
    assert list(out.iterdir()) == []


def test_jpeg_header_followed_by_garbage_is_not_image(tmp_path: Path) -> None:
    sources = _write_images(tmp_path, [b"\xff\xd8\xff" + b"garbage " * 50])
    out = _out(tmp_path)

    with pytest.raises(AppError) as info:
        convert_images_to_pdf(sources, out, "fit")

    assert info.value.code == NOT_IMAGE
    assert list(out.iterdir()) == []


def test_a_bad_second_file_is_named_by_position_and_leaves_nothing(
    tmp_path: Path,
) -> None:
    sources = _write_images(tmp_path, [_jpeg(), b"not an image at all" * 5])
    out = _out(tmp_path)

    with pytest.raises(AppError) as info:
        convert_images_to_pdf(sources, out, "fit")

    assert info.value.code == NOT_IMAGE
    assert "Image 2" in info.value.message
    assert list(out.iterdir()) == []


def test_too_many_pixels_is_too_large(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(engine, "_MAX_PIXELS", 100)
    sources = _write_images(tmp_path, [_jpeg(20, 20)])
    out = _out(tmp_path)

    with pytest.raises(AppError) as info:
        convert_images_to_pdf(sources, out, "fit")

    assert info.value.code == TOO_LARGE
    assert list(out.iterdir()) == []


def test_result_is_a_readable_pdf_with_the_reported_size(tmp_path: Path) -> None:
    sources = _write_images(tmp_path, [_jpeg(), _png()])
    out = _out(tmp_path)

    result = convert_images_to_pdf(sources, out, "fit")

    assert result.result_name == "result.pdf"
    assert result.result_size == (out / "result.pdf").stat().st_size
    assert [entry.name for entry in out.iterdir()] == ["result.pdf"]
    with pymupdf.open(str(out / "result.pdf")) as document:
        assert document.page_count == 2


def test_parse_page_size_accepts_only_fit_and_a4() -> None:
    assert parse_page_size("fit") == "fit"
    assert parse_page_size("a4") == "a4"
    for bad in ("A4", "a3", "", None, 1):
        with pytest.raises(AppError) as info:
            parse_page_size(bad)
        assert info.value.code == INVALID_PAGE_SIZE


def test_an_empty_input_list_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(AppError) as info:
        convert_images_to_pdf([], _out(tmp_path), "fit")

    assert info.value.code == INVALID_REQUEST


def test_concurrency_limit_is_enforced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MAX_CONCURRENT_JOBS", "2")
    get_settings.cache_clear()
    engine.rebuild_concurrency_gate()

    lock = threading.Lock()
    release = threading.Event()
    state = {"active": 0, "peak": 0, "entered": 0}

    def fake(
        input_paths: list[Path], output_dir: Path, page_size: str
    ) -> JpgToPdfResult:
        with lock:
            state["active"] += 1
            state["entered"] += 1
            state["peak"] = max(state["peak"], state["active"])
        try:
            release.wait(timeout=10)
        finally:
            with lock:
                state["active"] -= 1
        return JpgToPdfResult(1, 1, "result.pdf")

    monkeypatch.setattr(engine, "_convert_locked", fake)
    threads = [
        threading.Thread(
            target=convert_images_to_pdf,
            args=([tmp_path / "in.bin"], tmp_path / "out", "fit"),
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
def post_jpg_to_pdf(client: TestClient) -> PostJpgToPdf:
    """post_jpg_to_pdf([(name, bytes), ...], page_size="fit")."""

    def _post(
        files: list[tuple[str, bytes]], *, page_size: str | None = "fit"
    ) -> Response:
        parts = [
            ("files", (name, content, "application/octet-stream"))
            for name, content in files
        ]
        data = {} if page_size is None else {"page_size": page_size}
        return client.post("/api/jpg-to-pdf", files=parts, data=data)

    return _post


def test_multi_image_success_returns_every_contract_field(
    post_jpg_to_pdf: PostJpgToPdf, storage_dir: Path
) -> None:
    first = _jpeg(300, 200)
    second = _png(100, 150)

    response = post_jpg_to_pdf([("a.jpg", first), ("b.png", second)], page_size="a4")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == CONTRACT_FIELDS
    assert body["page_count"] == 2
    assert body["total_input_size"] == len(first) + len(second)
    assert body["page_size"] == "a4"
    assert body["download_name"] == "images.pdf"
    assert body["download_url"] == f"/api/jobs/{body['job_id']}/download"

    output_dir = storage_dir / "outputs" / body["job_id"]
    assert (output_dir / "result.pdf").stat().st_size == body["result_size"]
    meta = json.loads((output_dir / "meta.json").read_text(encoding="utf-8"))
    assert meta["result_name"] == "result.pdf"
    assert meta["download_name"] == "images.pdf"
    assert not (storage_dir / "uploads" / body["job_id"]).exists()


def test_single_image_download_name_follows_the_file_name(
    post_jpg_to_pdf: PostJpgToPdf,
) -> None:
    response = post_jpg_to_pdf([("Holiday photo.jpg", _jpeg())])

    assert response.status_code == 200
    assert response.json()["download_name"] == "Holiday photo.pdf"


def test_a_client_file_name_never_reaches_the_disk_or_the_download_name(
    post_jpg_to_pdf: PostJpgToPdf, storage_dir: Path
) -> None:
    response = post_jpg_to_pdf([("../../evil.jpg", _jpeg())])

    assert response.status_code == 200
    body = response.json()
    assert body["download_name"] == "evil.pdf"
    output_dir = storage_dir / "outputs" / body["job_id"]
    assert sorted(entry.name for entry in output_dir.iterdir()) == [
        "meta.json",
        "result.pdf",
    ]


def test_result_downloads_as_a_pdf_and_deletes_the_job(
    client: TestClient,
    post_jpg_to_pdf: PostJpgToPdf,
    job_entries: Callable[[], list[str]],
) -> None:
    job = post_jpg_to_pdf([("a.jpg", _jpeg()), ("b.jpg", _jpeg())]).json()

    response = client.get(str(job["download_url"]))

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["content-disposition"] == (
        'attachment; filename="images.pdf"'
    )
    assert response.content.startswith(b"%PDF-")
    assert len(response.content) == job["result_size"]
    assert job_entries() == []


@pytest.mark.parametrize("bad_size", ["a3", "A4", "", None])
def test_bad_or_missing_page_size_gives_invalid_page_size_and_creates_no_job(
    post_jpg_to_pdf: PostJpgToPdf,
    job_entries: Callable[[], list[str]],
    bad_size: str | None,
) -> None:
    response = post_jpg_to_pdf([("a.jpg", _jpeg())], page_size=bad_size)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == INVALID_PAGE_SIZE
    assert job_entries() == []


def test_missing_files_field_is_invalid_request(client: TestClient) -> None:
    response = client.post("/api/jpg-to-pdf", data={"page_size": "fit"})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == INVALID_REQUEST


def test_too_many_files_gives_413_and_leaves_no_files(
    post_jpg_to_pdf: PostJpgToPdf,
    job_entries: Callable[[], list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MAX_IMAGES", "2")
    get_settings.cache_clear()

    response = post_jpg_to_pdf([(f"{n}.jpg", _jpeg()) for n in range(3)])

    assert response.status_code == 413
    assert response.json()["error"]["code"] == TOO_MANY_FILES
    assert job_entries() == []


def test_non_image_gives_not_image_and_leaves_no_files(
    post_jpg_to_pdf: PostJpgToPdf, job_entries: Callable[[], list[str]]
) -> None:
    response = post_jpg_to_pdf([("x.jpg", b"plain text, not a picture. " * 20)])

    assert response.status_code == 400
    assert response.json()["error"]["code"] == NOT_IMAGE
    assert job_entries() == []


def test_empty_file_gives_not_image_with_a_helpful_message(
    post_jpg_to_pdf: PostJpgToPdf, job_entries: Callable[[], list[str]]
) -> None:
    response = post_jpg_to_pdf([("x.jpg", b"")])

    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == NOT_IMAGE
    assert "empty" in error["message"].lower()
    assert job_entries() == []


def test_total_size_over_the_limit_is_too_large(
    post_jpg_to_pdf: PostJpgToPdf,
    job_entries: Callable[[], list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MAX_UPLOAD_MB", "1")
    get_settings.cache_clear()
    big = b"\xff\xd8\xff" + os.urandom(700_000)  # each file fits, the pair does not

    response = post_jpg_to_pdf([("a.jpg", big), ("b.jpg", big)])

    assert response.status_code == 413
    error = response.json()["error"]
    assert error["code"] == TOO_LARGE
    assert "1 MB" in error["message"]
    assert job_entries() == []


def test_engine_failure_returns_processing_failed_without_details(
    post_jpg_to_pdf: PostJpgToPdf,
    job_entries: Callable[[], list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def explode(
        input_paths: list[Path], output_dir: Path, page_size: str
    ) -> JpgToPdfResult:
        raise RuntimeError("boom at /secret/path")

    monkeypatch.setattr(engine, "_convert_locked", explode)

    response = post_jpg_to_pdf([("a.jpg", _jpeg())])

    assert response.status_code == 500
    assert response.json()["error"]["code"] == PROCESSING_FAILED
    assert "secret" not in response.text
    assert job_entries() == []


def test_unexpected_error_returns_internal_error_and_cleans_up(
    post_jpg_to_pdf: PostJpgToPdf,
    job_entries: Callable[[], list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def explode(*args: object, **kwargs: object) -> None:
        raise RuntimeError("boom at /secret/path")

    monkeypatch.setattr(jpg_to_pdf_route, "convert_images_to_pdf", explode)

    response = post_jpg_to_pdf([("a.jpg", _jpeg())])

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert "secret" not in response.text
    assert job_entries() == []