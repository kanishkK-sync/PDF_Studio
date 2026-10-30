"""Shared test fixtures."""

import io
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path

import pymupdf
import pytest
from fastapi.testclient import TestClient
from httpx import Response
from PIL import Image, ImageOps

from app.core.config import get_settings
from app.main import app
from app.services.compress import rebuild_concurrency_gate
from app.services.jpg_to_pdf import rebuild_concurrency_gate as rebuild_jpg_to_pdf_gate
from app.services.pdf_to_jpg import rebuild_concurrency_gate as rebuild_pdf_to_jpg_gate


@pytest.fixture
def storage_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Point the storage directory at a fresh temporary folder.

    The folder is `<tmp>/storage`, so tests can use its parent as a place
    outside storage. Sets STORAGE_DIR through the environment and clears the
    settings cache before and after; monkeypatch restores the environment.
    """
    root = tmp_path / "storage"
    root.mkdir()
    monkeypatch.setenv("STORAGE_DIR", str(root))
    get_settings.cache_clear()
    yield root
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _reset_concurrency_gate() -> Iterator[None]:
    """Rebuild the engine's concurrency gate after every test.

    Tests that change MAX_CONCURRENT_JOBS must not leak the new limit into
    later tests. Runs after monkeypatch has restored the environment.
    """
    yield
    get_settings.cache_clear()
    rebuild_concurrency_gate()


@pytest.fixture(autouse=True)
def _reset_pdf_to_jpg_gate() -> Iterator[None]:
    """The same reset for the PDF to JPG engine's own gate."""
    yield
    get_settings.cache_clear()
    rebuild_pdf_to_jpg_gate()


@pytest.fixture(autouse=True)
def _reset_jpg_to_pdf_gate() -> Iterator[None]:
    """The same reset for the JPG to PDF engine's own gate."""
    yield
    get_settings.cache_clear()
    rebuild_jpg_to_pdf_gate()


# -- PDF builders --------------------------------------------------------------


def _smooth_png(width: int, height: int) -> bytes:
    """A smooth, photo-like image. Random noise would not compress as JPEG."""
    vertical = Image.linear_gradient("L").resize(
        (width, height), Image.Resampling.BILINEAR
    )
    radial = Image.radial_gradient("L").resize(
        (width, height), Image.Resampling.BICUBIC
    )
    image = Image.merge("RGB", (vertical, radial, ImageOps.invert(vertical)))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _build_pdf(
    path: Path,
    *,
    pages: int = 3,
    with_image: bool = False,
    title: str = "Test document",
) -> Path:
    """Write a PDF with real text, a link, bookmarks, metadata and maybe a photo.

    The image is 1600x1200 px placed at 400x300 pt, about 288 effective DPI,
    so both balanced and strong must resample it.
    """
    document = pymupdf.open()
    try:
        png = _smooth_png(1600, 1200) if with_image else None
        for number in range(1, pages + 1):
            page = document.new_page(width=595, height=842)
            for line in range(18):
                page.insert_text(
                    (72, 72 + 16 * line),
                    f"Page {number} line {line}: the quick brown fox jumps over "
                    "the lazy dog",
                    fontsize=11,
                )
            if png is not None:
                page.insert_image(pymupdf.Rect(96, 400, 496, 700), stream=png)
        document.load_page(0).insert_link(
            {
                "kind": pymupdf.LINK_URI,
                "from": pymupdf.Rect(72, 60, 200, 74),
                "uri": "https://example.com",
            }
        )
        if pages >= 2:
            document.set_toc([[1, "First chapter", 1], [1, "Second chapter", 2]])
        document.set_metadata({"title": title, "author": "Test Author"})
        document.save(str(path))
    finally:
        document.close()
    return path


def _build_encrypted_pdf(path: Path) -> Path:
    document = pymupdf.open()
    try:
        page = document.new_page()
        page.insert_text((72, 72), "secret contents", fontsize=12)
        document.save(
            str(path),
            encryption=pymupdf.PDF_ENCRYPT_AES_256,
            user_pw="user-secret",
            owner_pw="owner-secret",
        )
    finally:
        document.close()
    return path


@pytest.fixture
def pdf_factory() -> Callable[..., Path]:
    """The PDF builder: pdf_factory(path, pages=3, with_image=False, title=...)."""
    return _build_pdf


@pytest.fixture(scope="session")
def _image_pdf_bytes(tmp_path_factory: pytest.TempPathFactory) -> bytes:
    path = _build_pdf(
        tmp_path_factory.mktemp("pdfs") / "image.pdf", pages=4, with_image=True
    )
    return path.read_bytes()


@pytest.fixture(scope="session")
def _text_pdf_bytes(tmp_path_factory: pytest.TempPathFactory) -> bytes:
    path = _build_pdf(tmp_path_factory.mktemp("pdfs") / "text.pdf", pages=8)
    return path.read_bytes()


@pytest.fixture
def image_pdf(tmp_path: Path, _image_pdf_bytes: bytes) -> Path:
    """A 4-page image-heavy PDF outside storage."""
    path = tmp_path / "image.pdf"
    path.write_bytes(_image_pdf_bytes)
    return path


@pytest.fixture
def text_pdf(tmp_path: Path, _text_pdf_bytes: bytes) -> Path:
    """An 8-page text-only PDF outside storage."""
    path = tmp_path / "text.pdf"
    path.write_bytes(_text_pdf_bytes)
    return path


@pytest.fixture
def encrypted_pdf(tmp_path: Path) -> Path:
    """A PDF that needs a password to open."""
    return _build_encrypted_pdf(tmp_path / "encrypted.pdf")


# -- App client ----------------------------------------------------------------


@pytest.fixture
def client(storage_dir: Path) -> Iterator[TestClient]:
    """A client with the lifespan running, bound to a temporary storage folder.

    Depends on storage_dir on purpose: the lifespan empties storage on startup,
    which must never touch the real folder.
    """
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


@pytest.fixture
def post_compress(client: TestClient) -> Callable[..., Response]:
    """post_compress(content, level="balanced", filename="report.pdf")."""

    def _post(
        content: bytes,
        *,
        level: str | None = "balanced",
        filename: str = "report.pdf",
        content_type: str = "application/pdf",
    ) -> Response:
        data = {} if level is None else {"level": level}
        return client.post(
            "/api/compress",
            files={"file": (filename, content, content_type)},
            data=data,
        )

    return _post


@pytest.fixture
def post_pdf_to_jpg(client: TestClient) -> Callable[..., Response]:
    """post_pdf_to_jpg(content, quality="medium", filename="report.pdf")."""

    def _post(
        content: bytes,
        *,
        quality: str | None = "medium",
        filename: str = "report.pdf",
        content_type: str = "application/pdf",
    ) -> Response:
        data = {} if quality is None else {"quality": quality}
        return client.post(
            "/api/pdf-to-jpg",
            files={"file": (filename, content, content_type)},
            data=data,
        )

    return _post


@pytest.fixture
def post_jpg_to_pdf(client: TestClient) -> Callable[..., Response]:
    """post_jpg_to_pdf([(name, content), ...], page_size="fit").

    Every part is sent as image/jpeg on purpose: the server must go by the
    bytes, never by the declared type.
    """

    def _post(
        files: Sequence[tuple[str, bytes]],
        *,
        page_size: str | None = "fit",
    ) -> Response:
        data = {} if page_size is None else {"page_size": page_size}
        return client.post(
            "/api/jpg-to-pdf",
            files=[("files", (name, content, "image/jpeg")) for name, content in files],
            data=data,
        )

    return _post


@pytest.fixture
def job_entries(storage_dir: Path) -> Callable[[], list[str]]:
    """A function listing every job folder currently in storage."""

    def _list() -> list[str]:
        names: list[str] = []
        for kind in ("uploads", "outputs"):
            folder = storage_dir / kind
            if folder.exists():
                names.extend(f"{kind}/{entry.name}" for entry in folder.iterdir())
        return sorted(names)

    return _list