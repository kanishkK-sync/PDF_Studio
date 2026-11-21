"""Exercise the public upload, one-shot download, report and rendered pixels."""

import io
import json
from zipfile import ZipFile

import pikepdf
import pymupdf
import pytest
from PIL import Image

from app.core.config import get_settings
from app.services.pdf_compare import CYAN, MAGENTA


def pdf(lines, *, size=(144, 144), box=None):
    with pymupdf.open() as doc:
        for line in lines:
            page = doc.new_page(width=size[0], height=size[1])
            if line:
                page.insert_text((12, 25), line)
            if box:
                page.draw_rect(box, fill=(0, 0, 0), color=None)
        return doc.tobytes()


def post(client, original, revised):
    return client.post(
        "/api/compare-pdf",
        files={
            "original": ("original.pdf", original, "application/pdf"),
            "revised": ("revised.pdf", revised, "application/pdf"),
        },
    )


def read_job(client, response):
    assert response.status_code == 200, response.text
    job = response.json()
    download = client.get(job["download_url"])
    assert download.headers["content-type"] == "application/zip"
    with ZipFile(io.BytesIO(download.content)) as archive:
        assert archive.testzip() is None
        report = json.loads(archive.read("diff-report.json"))
        summary = archive.read("diff-summary.txt").decode()
        assert (
            f"Compared {report['compared_pages']} of {report['total_pages']}" in summary
        )
        names = [p["image"] for p in report["pages"]]
        assert names == [f"page-{n:03d}-diff.png" for n in range(1, len(names) + 1)]
        assert set(archive.namelist()) == {
            *names,
            "diff-summary.txt",
            "diff-report.json",
        }
        images = [archive.read(name) for name in names]
    for header, key in [
        ("X-Compared-Pages", "compared_pages"),
        ("X-Pages-Changed", "pages_changed"),
        ("X-Total-Pages", "total_pages"),
        ("X-Overall-Similarity", "overall_similarity"),
    ]:
        assert float(response.headers[header]) == report[key] == job[key]
    assert response.headers["X-Truncated"] == str(report["truncated"]).lower()
    assert client.get(job["download_url"]).status_code == 404
    return report, images


def test_identical(client):
    source = pdf(["An unchanged page", "Second page"])
    report, images = read_job(client, post(client, source, source))
    assert report["pages_changed"] == 0
    assert report["overall_similarity"] == 100 and not report["truncated"]
    for page, data in zip(report["pages"], images, strict=True):
        assert page["status"] == "unchanged" and not page["has_visual_changes"]
        assert page["added_lines"] == page["removed_lines"] == []
        assert page["dpi"] == 120
        with Image.open(io.BytesIO(data)) as image:
            assert image.size == (240, 240)
            assert all(r == g == b for _, (r, g, b) in image.getcolors())


def test_text_added_removed(client):
    report, _ = read_job(
        client, post(client, pdf(["Pay on Monday"]), pdf(["Pay on Friday"]))
    )
    page = report["pages"][0]
    assert page["added_lines"] == ["Pay on Friday"]
    assert page["removed_lines"] == ["Pay on Monday"]
    assert page["has_visual_changes"] and 0 < page["similarity_percent"] < 100


def test_graphics_only_moves_in_both_colors(client):
    left = pdf([""], box=(10, 60, 30, 80))
    right = pdf([""], box=(90, 60, 110, 80))
    report, images = read_job(client, post(client, left, right))
    page = report["pages"][0]
    assert page["has_visual_changes"] and page["status"] == "modified"
    assert page["added_lines"] == page["removed_lines"] == []
    assert report["overall_similarity"] < 100
    with Image.open(io.BytesIO(images[0])) as overlay:
        assert overlay.getpixel((33, 117)) == MAGENTA
        assert overlay.getpixel((167, 117)) == CYAN


@pytest.mark.parametrize("status", ["added", "removed"])
def test_extra_blank_page(client, status):
    short, long = pdf(["same"]), pdf(["same", ""])
    pair = (short, long) if status == "added" else (long, short)
    report, _ = read_job(client, post(client, *pair))
    assert report["total_pages"] == 2 and report["pages_changed"] == 1
    assert report["overall_similarity"] == 50
    page = report["pages"][1]
    assert page["status"] == status and page["has_visual_changes"]


def test_page_cap_excludes_later_changes(client):
    original = pdf([""] * 25, size=(40, 40))
    revised = pdf([""] * 26, size=(40, 40))
    report, images = read_job(client, post(client, original, revised))
    assert report["truncated"] and len(images) == report["compared_pages"] == 25
    assert report["total_pages"] == 26 and report["pages_changed"] == 0


def test_joint_canvas_clamped_for_opposite_aspect_ratios(client, monkeypatch):
    monkeypatch.setenv("MAX_RENDER_PIXELS", "80000")
    get_settings.cache_clear()
    report, images = read_job(
        client, post(client, pdf([""], size=(2200, 100)), pdf([""], size=(100, 2200)))
    )
    assert 1 <= report["pages"][0]["dpi"] < 120
    with Image.open(io.BytesIO(images[0])) as image:
        assert image.width == image.height and image.width * image.height <= 80000
    assert report["pages"][0]["has_visual_changes"]


@pytest.mark.parametrize("role", ["original", "revised"])
@pytest.mark.parametrize("problem", ["encrypted", "corrupt", "zero_pages"])
def test_input_guards_and_cleanup(client, storage_dir, encrypted_pdf, role, problem):
    data = b"%PDF-1.7\nbroken"
    if problem == "encrypted":
        data = encrypted_pdf.read_bytes()
    elif problem == "zero_pages":
        with io.BytesIO() as stream, pikepdf.Pdf.new() as doc:
            doc.save(stream)
            data = stream.getvalue()
    good = pdf(["OK"])
    response = (
        post(client, data, good) if role == "original" else post(client, good, data)
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == (
        "corrupt" if problem == "zero_pages" else problem
    )
    assert not any(path.is_file() for path in storage_dir.rglob("*"))


def test_combined_upload_limit(client, storage_dir, monkeypatch):
    monkeypatch.setenv("MAX_UPLOAD_MB", "1")
    get_settings.cache_clear()
    data = pdf(["ok"]) + b" " * (600 * 1024)
    response = post(client, data, data)
    assert (
        response.status_code == 413 and response.json()["error"]["code"] == "too_large"
    )
    assert not any(path.is_file() for path in storage_dir.rglob("*"))


def test_structural_change_with_identical_visible_pixels(client):
    def invisible(text):
        with pymupdf.open() as doc:
            page = doc.new_page(width=144, height=144)
            page.insert_text((12, 25), text, render_mode=3)
            return doc.tobytes()

    report, _ = read_job(client, post(client, invisible("draft"), invisible("final")))
    page = report["pages"][0]
    assert page["status"] == "modified" and not page["has_visual_changes"]
    assert page["removed_lines"] == ["draft"] and page["added_lines"] == ["final"]


def test_failure_on_later_page_discards_partial_archive(
    client, storage_dir, monkeypatch
):
    monkeypatch.setenv("MAX_RENDER_PIXELS", "1000")
    get_settings.cache_clear()
    with pymupdf.open() as doc:
        doc.new_page(width=30, height=30)
        doc.new_page(width=14400, height=14400)
        data = doc.tobytes()
    response = post(client, data, data)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "page_too_large"
    assert not any(path.is_file() for path in storage_dir.rglob("*"))
