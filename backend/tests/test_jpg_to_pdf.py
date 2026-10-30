"""Tests for the JPG/PNG to PDF engine and POST /api/jpg-to-pdf."""

import io
import json
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pymupdf
import pytest
from fastapi.testclient import TestClient
from httpx import Response
from PIL import Image

from app.api.routes import jobs as jobs_route
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
from app.utils.uploads import looks_like_jpeg, looks_like_png

PostJpgToPdf = Callable[..., Response]

POINTS_PER_MM = 72 / 25.4
A4_SHORT = 210 * POINTS_PER_MM
A4_LONG = 297 * POINTS_PER_MM
MARGIN = 10 * POINTS_PER_MM
CONTRACT_FIELDS = {
    "job_id",
    "page_count",
    "total_input_size",
    "result_size",
    "page_size",
    "download_url",
}


# -- Helpers -------------------------------------------------------------------


def _encode(image: Image.Image, image_format: str, **options: Any) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format=image_format, **options)
    return buffer.getvalue()


def _jpeg(
    size: tuple[int, int], color: Any, mode: str = "RGB", **options: Any
) -> bytes:
    options.setdefault("quality", 95)
    return _encode(Image.new(mode, size, color), "JPEG", **options)


def _png(image: Image.Image) -> bytes:
    return _encode(image, "PNG")


def _noise() -> Image.Image:
    """Noise compresses badly, so cutting the file in half really truncates it."""
    return Image.effect_noise((128, 128), 64).convert("RGB")


def _write(folder: Path, name: str, data: bytes) -> Path:
    path = folder / name
    path.write_bytes(data)
    return path


def _out(tmp_path: Path) -> Path:
    folder = tmp_path / "out"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _sizes(pdf: Path) -> list[tuple[float, float]]:
    document = pymupdf.open(str(pdf))
    try:
        return [(page.rect.width, page.rect.height) for page in document]
    finally:
        document.close()


def _pixel(pdf: Path, page_number: int, x: int, y: int) -> tuple[int, ...]:
    """The colour of one pixel of a page rendered at 72 DPI (1 point = 1 pixel)."""
    document = pymupdf.open(str(pdf))
    try:
        pixmap = document.load_page(page_number).get_pixmap(dpi=72, alpha=False)
        return tuple(pixmap.pixel(x, y))
    finally:
        document.close()


def _image_rect(pdf: Path, page_number: int) -> pymupdf.Rect:
    document = pymupdf.open(str(pdf))
    try:
        page = document.load_page(page_number)
        xref = page.get_images(full=True)[0][0]
        return page.get_image_rects(xref)[0]
    finally:
        document.close()


def _embedded_image(pdf: Path, page_number: int) -> bytes:
    document = pymupdf.open(str(pdf))
    try:
        xref = document.load_page(page_number).get_images(full=True)[0][0]
        return document.extract_image(xref)["image"]
    finally:
        document.close()


def _near(actual: tuple[int, ...], expected: tuple[int, int, int], tolerance: int) -> bool:
    return all(
        abs(a - e) <= tolerance for a, e in zip(actual, expected, strict=True)
    )


def _wait_until(predicate: Callable[[], bool], timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


# -- Engine --------------------------------------------------------------------


def test_pages_follow_the_order_of_the_files_and_mix_formats(tmp_path: Path) -> None:
    paths = [
        _write(tmp_path, "a.bin", _jpeg((30, 20), (255, 0, 0))),
        _write(tmp_path, "b.bin", _png(Image.new("RGB", (20, 30), (0, 255, 0)))),
        _write(tmp_path, "c.bin", _jpeg((40, 40), (0, 0, 255))),
    ]
    out = _out(tmp_path)

    result = convert_images_to_pdf(paths, out, "fit")

    pdf = out / "result.pdf"
    assert result.page_count == 3
    assert result.page_size == "fit"
    assert result.result_name == "result.pdf"
    assert result.total_input_size == sum(path.stat().st_size for path in paths)
    assert result.result_size == pdf.stat().st_size
    expected_sizes = [(30, 20), (20, 30), (40, 40)]
    for size, expected in zip(_sizes(pdf), expected_sizes, strict=True):
        assert size == pytest.approx(expected, abs=0.01)
    assert _near(_pixel(pdf, 0, 15, 10), (255, 0, 0), 30)
    assert _near(_pixel(pdf, 1, 10, 15), (0, 255, 0), 30)
    assert _near(_pixel(pdf, 2, 20, 20), (0, 0, 255), 30)


def test_fit_honours_the_embedded_dpi(tmp_path: Path) -> None:
    path = _write(tmp_path, "a.bin", _jpeg((144, 72), (10, 120, 200), dpi=(144, 144)))
    out = _out(tmp_path)

    convert_images_to_pdf([path], out, "fit")

    width, height = _sizes(out / "result.pdf")[0]
    assert width == pytest.approx(72, abs=0.01)
    assert height == pytest.approx(36, abs=0.01)


def test_a_very_large_fit_page_is_capped_at_the_pdf_limit(tmp_path: Path) -> None:
    path = _write(tmp_path, "wide.bin", _jpeg((20000, 100), (90, 90, 90)))
    out = _out(tmp_path)

    convert_images_to_pdf([path], out, "fit")

    width, height = _sizes(out / "result.pdf")[0]
    assert width == pytest.approx(14400, abs=0.01)
    assert height == pytest.approx(72, abs=0.01)


def test_a4_pages_are_a4_centred_with_a_10_mm_margin(tmp_path: Path) -> None:
    images = [(60, 100), (100, 60), (80, 80)]
    paths = [
        _write(tmp_path, f"{index}.bin", _jpeg(size, (200, 100, 50)))
        for index, size in enumerate(images)
    ]
    out = _out(tmp_path)

    convert_images_to_pdf(paths, out, "a4")

    pdf = out / "result.pdf"
    pages = [(A4_SHORT, A4_LONG), (A4_LONG, A4_SHORT), (A4_SHORT, A4_LONG)]
    for number, (image, page) in enumerate(zip(images, pages, strict=True)):
        page_width, page_height = page
        assert _sizes(pdf)[number] == pytest.approx(page, abs=0.01)
        rect = _image_rect(pdf, number)
        assert rect.x0 >= MARGIN - 0.5
        assert rect.y0 >= MARGIN - 0.5
        assert rect.x1 <= page_width - MARGIN + 0.5
        assert rect.y1 <= page_height - MARGIN + 0.5
        assert (rect.x0 + rect.x1) / 2 == pytest.approx(page_width / 2, abs=0.5)
        assert (rect.y0 + rect.y1) / 2 == pytest.approx(page_height / 2, abs=0.5)
        assert rect.width / rect.height == pytest.approx(
            image[0] / image[1], rel=0.01
        )
        fills_width = abs(rect.width - (page_width - 2 * MARGIN)) < 0.5
        fills_height = abs(rect.height - (page_height - 2 * MARGIN)) < 0.5
        assert fills_width or fills_height


def test_a_cmyk_jpeg_is_converted_and_keeps_its_colours(tmp_path: Path) -> None:
    cmyk = Image.new("RGB", (64, 64), (200, 30, 30)).convert("CMYK")
    path = _write(tmp_path, "a.bin", _encode(cmyk, "JPEG", quality=95))
    out = _out(tmp_path)

    convert_images_to_pdf([path], out, "fit")

    pdf = out / "result.pdf"
    assert _sizes(pdf)[0] == pytest.approx((64, 64), abs=0.01)
    assert _near(_pixel(pdf, 0, 32, 32), (200, 30, 30), 40)


def test_a_grayscale_jpeg_is_embedded_byte_for_byte(tmp_path: Path) -> None:
    original = _jpeg((64, 64), 128, mode="L")
    path = _write(tmp_path, "a.bin", original)
    out = _out(tmp_path)

    convert_images_to_pdf([path], out, "fit")

    pdf = out / "result.pdf"
    assert _embedded_image(pdf, 0) == original
    assert _near(_pixel(pdf, 0, 32, 32), (128, 128, 128), 12)


def test_a_progressive_jpeg_is_embedded_byte_for_byte(tmp_path: Path) -> None:
    original = _jpeg((64, 64), (30, 160, 90), progressive=True)
    path = _write(tmp_path, "a.bin", original)
    out = _out(tmp_path)

    convert_images_to_pdf([path], out, "fit")

    pdf = out / "result.pdf"
    assert _embedded_image(pdf, 0) == original
    assert _near(_pixel(pdf, 0, 32, 32), (30, 160, 90), 25)


def test_exif_orientation_is_honoured(tmp_path: Path) -> None:
    image = Image.new("RGB", (64, 32), (255, 0, 0))
    image.paste((0, 0, 255), (32, 0, 64, 32))  # left half red, right half blue
    exif = Image.Exif()
    exif[0x0112] = 6  # display rotated 90 degrees clockwise
    data = _encode(image, "JPEG", quality=95, exif=exif.tobytes())
    path = _write(tmp_path, "a.bin", data)
    out = _out(tmp_path)

    convert_images_to_pdf([path], out, "fit")

    pdf = out / "result.pdf"
    assert _sizes(pdf)[0] == pytest.approx((32, 64), abs=0.01)
    assert _near(_pixel(pdf, 0, 16, 8), (255, 0, 0), 60)  # the left half is now on top
    assert _near(_pixel(pdf, 0, 16, 56), (0, 0, 255), 60)


def test_png_transparency_is_flattened_onto_white(tmp_path: Path) -> None:
    image = Image.new("RGBA", (40, 40), (0, 0, 255, 0))  # fully transparent
    image.paste((255, 0, 0, 255), (0, 0, 40, 20))  # opaque red on top
    path = _write(tmp_path, "a.bin", _png(image))
    out = _out(tmp_path)

    convert_images_to_pdf([path], out, "fit")

    pdf = out / "result.pdf"
    assert _near(_pixel(pdf, 0, 20, 5), (255, 0, 0), 6)
    assert _near(_pixel(pdf, 0, 20, 35), (255, 255, 255), 6)


def test_a_palette_png_is_converted(tmp_path: Path) -> None:
    palette = Image.new("RGB", (30, 30), (10, 200, 50)).quantize(colors=4)
    assert palette.mode == "P"
    path = _write(tmp_path, "a.bin", _png(palette))
    out = _out(tmp_path)

    convert_images_to_pdf([path], out, "fit")

    assert _near(_pixel(out / "result.pdf", 0, 15, 15), (10, 200, 50), 10)


def test_a_16_bit_png_is_converted_without_clipping_to_white(tmp_path: Path) -> None:
    image = Image.new("I;16", (32, 32), 40000)
    path = _write(tmp_path, "a.bin", _png(image))
    out = _out(tmp_path)

    convert_images_to_pdf([path], out, "fit")

    assert _near(_pixel(out / "result.pdf", 0, 16, 16), (156, 156, 156), 4)


def test_garbage_behind_a_jpeg_header_names_the_image_and_leaves_no_files(
    tmp_path: Path,
) -> None:
    good = _write(tmp_path, "a.bin", _jpeg((16, 16), (1, 2, 3)))
    bad = _write(tmp_path, "b.bin", b"\xff\xd8\xff\xe0" + b"garbage" * 100)
    out = _out(tmp_path)

    with pytest.raises(AppError) as info:
        convert_images_to_pdf([good, bad], out, "fit")

    assert info.value.code == NOT_IMAGE
    assert "Image 2" in info.value.message
    assert list(out.iterdir()) == []


def test_a_truncated_jpeg_is_not_an_image(tmp_path: Path) -> None:
    data = _encode(_noise(), "JPEG", quality=90)
    path = _write(tmp_path, "a.bin", data[: len(data) // 2])
    out = _out(tmp_path)

    with pytest.raises(AppError) as info:
        convert_images_to_pdf([path], out, "fit")

    assert info.value.code == NOT_IMAGE
    assert list(out.iterdir()) == []


def test_the_pixel_cap_rejects_huge_images(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(engine, "_MAX_IMAGE_PIXELS", 100)
    path = _write(tmp_path, "a.bin", _jpeg((20, 20), (1, 2, 3)))
    out = _out(tmp_path)

    with pytest.raises(AppError) as info:
        convert_images_to_pdf([path], out, "fit")

    assert info.value.code == TOO_LARGE
    assert "Image 1" in info.value.message
    assert "pixels" in info.value.message
    assert list(out.iterdir()) == []


def test_a_pymupdf_refusal_falls_back_to_a_re_encode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = _jpeg((64, 64), (30, 160, 90))
    path = _write(tmp_path, "a.bin", original)
    real_insert = engine._insert_image
    sources: list[Path] = []

    def flaky(page: Any, rect: Any, source: Path) -> None:
        sources.append(source)
        if len(sources) == 1:
            raise ValueError("MuPDF refused this image")
        real_insert(page, rect, source)

    monkeypatch.setattr(engine, "_insert_image", flaky)
    out = _out(tmp_path)

    result = convert_images_to_pdf([path], out, "fit")

    pdf = out / "result.pdf"
    assert result.page_count == 1
    assert sources[0] == path
    assert sources[1] != path
    assert _embedded_image(pdf, 0) != original
    assert _near(_pixel(pdf, 0, 32, 32), (30, 160, 90), 30)


def test_concurrency_limit_is_enforced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MAX_CONCURRENT_JOBS", "2")
    get_settings.cache_clear()
    engine.rebuild_concurrency_gate()

    lock = threading.Lock()
    release = threading.Event()
    state = {"active": 0, "peak": 0, "entered": 0}

    def fake(image_paths: Any, output_dir: Path, page_size: str) -> JpgToPdfResult:
        with lock:
            state["active"] += 1
            state["entered"] += 1
            state["peak"] = max(state["peak"], state["active"])
        try:
            release.wait(timeout=10)
        finally:
            with lock:
                state["active"] -= 1
        return JpgToPdfResult(1, 1, 1, "fit", "result.pdf")

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


def test_parse_page_size_accepts_only_fit_and_a4() -> None:
    for page_size in ("fit", "a4"):
        assert parse_page_size(page_size) == page_size
    for bad in ("A4", "letter", "", None, 1):
        with pytest.raises(AppError) as info:
            parse_page_size(bad)
        assert info.value.code == INVALID_PAGE_SIZE


def test_work_folder_is_removed_after_success(tmp_path: Path) -> None:
    path = _write(tmp_path, "a.bin", _jpeg((16, 16), (1, 2, 3)))
    out = _out(tmp_path)

    convert_images_to_pdf([path], out, "fit")

    assert [entry.name for entry in out.iterdir()] == ["result.pdf"]


def test_signature_helpers_look_at_the_first_bytes_only(tmp_path: Path) -> None:
    jpeg = _write(tmp_path, "j.bin", b"\xff\xd8\xff\xe0" + b"x" * 10)
    png = _write(tmp_path, "p.bin", b"\x89PNG\r\n\x1a\n" + b"x" * 10)
    pdf = _write(tmp_path, "d.bin", b"%PDF-1.4 hello")
    short = _write(tmp_path, "s.bin", b"\xff\xd8")
    shifted = _write(tmp_path, "o.bin", b"\x00\xff\xd8\xff" + b"x" * 10)
    empty = _write(tmp_path, "e.bin", b"")

    assert looks_like_jpeg(jpeg)
    assert not looks_like_png(jpeg)
    assert looks_like_png(png)
    assert not looks_like_jpeg(png)
    for other in (pdf, short, shifted, empty):
        assert not looks_like_jpeg(other)
        assert not looks_like_png(other)


def test_engine_result_name_is_in_the_download_allowlist() -> None:
    assert engine.RESULT_PDF in jobs_route.RESULT_TYPES
    assert jobs_route.RESULT_TYPES[engine.RESULT_PDF][0] == "application/pdf"


# -- Route ---------------------------------------------------------------------


def test_success_returns_every_contract_field_and_keeps_the_page_order(
    client: TestClient,
    post_jpg_to_pdf: PostJpgToPdf,
    storage_dir: Path,
    tmp_path: Path,
) -> None:
    files = [
        ("one.jpg", _jpeg((30, 20), (255, 0, 0))),
        ("two.png", _png(Image.new("RGB", (20, 30), (0, 255, 0)))),
    ]

    response = post_jpg_to_pdf(files, page_size="fit")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == CONTRACT_FIELDS
    assert body["page_count"] == 2
    assert body["total_input_size"] == sum(len(content) for _name, content in files)
    assert body["page_size"] == "fit"
    assert body["download_url"] == f"/api/jobs/{body['job_id']}/download"

    output_dir = storage_dir / "outputs" / body["job_id"]
    assert (output_dir / "result.pdf").stat().st_size == body["result_size"]
    meta = json.loads((output_dir / "meta.json").read_text(encoding="utf-8"))
    assert meta["result_name"] == "result.pdf"
    assert meta["download_name"] == "images.pdf"
    assert not (storage_dir / "uploads" / body["job_id"]).exists()

    download = client.get(body["download_url"])
    assert download.status_code == 200
    pdf = _write(tmp_path, "downloaded.pdf", download.content)
    for size, expected in zip(_sizes(pdf), [(30, 20), (20, 30)], strict=True):
        assert size == pytest.approx(expected, abs=0.01)


@pytest.mark.parametrize(
    ("names", "expected"),
    [
        (["photo.jpg"], 'attachment; filename="photo.pdf"'),
        (["a.jpg", "b.png"], 'attachment; filename="images.pdf"'),
        (["Café.jpg"], "filename*=utf-8''Caf%C3%A9.pdf"),
    ],
)
def test_download_names_follow_the_file_count(
    client: TestClient,
    post_jpg_to_pdf: PostJpgToPdf,
    names: list[str],
    expected: str,
) -> None:
    files = [(name, _jpeg((16, 16), (10, 20, 30))) for name in names]
    job = post_jpg_to_pdf(files).json()

    response = client.get(job["download_url"])

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["cache-control"] == "no-store"
    assert expected in response.headers["content-disposition"]
    assert response.content.startswith(b"%PDF-")


@pytest.mark.parametrize("page_size", ["A4", "letter", "", None])
def test_bad_or_missing_page_size_gives_invalid_page_size_and_creates_no_job(
    post_jpg_to_pdf: PostJpgToPdf,
    job_entries: Callable[[], list[str]],
    page_size: str | None,
) -> None:
    files = [("a.jpg", _jpeg((16, 16), (1, 2, 3)))]

    response = post_jpg_to_pdf(files, page_size=page_size)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == INVALID_PAGE_SIZE
    assert job_entries() == []


def test_missing_files_field_is_invalid_request(client: TestClient) -> None:
    response = client.post("/api/jpg-to-pdf", data={"page_size": "fit"})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == INVALID_REQUEST


def test_too_many_files_gives_413_and_creates_no_job(
    post_jpg_to_pdf: PostJpgToPdf,
    job_entries: Callable[[], list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MAX_IMAGES", "2")
    get_settings.cache_clear()
    files = [(f"{index}.jpg", _jpeg((16, 16), (1, 2, 3))) for index in range(3)]

    response = post_jpg_to_pdf(files)

    assert response.status_code == 413
    error = response.json()["error"]
    assert error["code"] == TOO_MANY_FILES
    assert "3" in error["message"]
    assert "2" in error["message"]
    assert job_entries() == []


def test_the_size_cap_applies_to_the_total_of_all_files(
    post_jpg_to_pdf: PostJpgToPdf,
    job_entries: Callable[[], list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MAX_UPLOAD_MB", "1")
    get_settings.cache_clear()
    # Each file is under 1 MB; together they are over.
    content = b"\xff\xd8\xff" + b"\x00" * 599_997
    files = [("a.jpg", content), ("b.jpg", content)]

    response = post_jpg_to_pdf(files)

    assert response.status_code == 413
    error = response.json()["error"]
    assert error["code"] == TOO_LARGE
    assert "1 MB" in error["message"]
    assert "in total" in error["message"]
    assert job_entries() == []


@pytest.mark.parametrize(
    "content",
    [
        b"hello, this is not an image. " * 10,
        b"%PDF-1.4\n%%EOF",
        b"GIF89a" + b"\x00" * 50,
        b"",
    ],
    ids=["text", "pdf", "gif", "empty"],
)
def test_a_file_that_is_not_a_jpeg_or_png_is_not_an_image(
    post_jpg_to_pdf: PostJpgToPdf,
    job_entries: Callable[[], list[str]],
    content: bytes,
) -> None:
    response = post_jpg_to_pdf([("photo.jpg", content)])

    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == NOT_IMAGE
    assert "Image 1" in error["message"]
    assert job_entries() == []


def _damaged(kind: str) -> bytes:
    if kind == "garbage_jpeg":
        return b"\xff\xd8\xff\xe0" + b"garbage" * 100
    if kind == "truncated_jpeg":
        data = _encode(_noise(), "JPEG", quality=90)
    else:
        data = _encode(_noise(), "PNG")
    return data[: len(data) // 2]


@pytest.mark.parametrize("kind", ["garbage_jpeg", "truncated_jpeg", "truncated_png"])
def test_a_damaged_image_is_not_an_image_and_leaves_no_files(
    post_jpg_to_pdf: PostJpgToPdf,
    job_entries: Callable[[], list[str]],
    kind: str,
) -> None:
    files = [
        ("ok.jpg", _jpeg((16, 16), (1, 2, 3))),
        ("bad.jpg", _damaged(kind)),
    ]

    response = post_jpg_to_pdf(files)

    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == NOT_IMAGE
    assert "Image 2" in error["message"]
    assert job_entries() == []


def test_engine_failure_returns_processing_failed_without_details(
    post_jpg_to_pdf: PostJpgToPdf,
    job_entries: Callable[[], list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def explode(image_paths: Any, output_dir: Path, page_size: str) -> JpgToPdfResult:
        raise RuntimeError("boom at /secret/path")

    monkeypatch.setattr(engine, "_convert_locked", explode)

    response = post_jpg_to_pdf([("a.jpg", _jpeg((16, 16), (1, 2, 3)))])

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

    response = post_jpg_to_pdf([("a.jpg", _jpeg((16, 16), (1, 2, 3)))])

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert "secret" not in response.text
    assert job_entries() == []