import pymupdf
import pytest


def sample():
    with pymupdf.open() as doc:
        page = doc.new_page()
        page.insert_text((40, 40), "Private phrase / Private phrase / public")
        page.insert_text((40, 80), "alex@example.org (212) 555-1212 123-45-6789")
        page.insert_text((40, 120), "4111 1111 1111 1111 https://example.org")
        page.add_text_annot((100, 200), "secret comment")
        doc.set_metadata({"author": "secret author"})
        doc.set_xml_metadata("<metadata>secret XMP</metadata>")
        doc.embfile_add("notes.txt", b"secret attachment")
        return doc.tobytes()


@pytest.mark.parametrize("scrub", [True, False])
def test_saved_pdf_and_audit(client, scrub):
    response = client.post(
        "/api/redact-pdf",
        files={"file": ("private.pdf", sample())},
        data={
            "terms": "Private phrase",
            "presets": "emails,phones,ssn,cards,urls",
            "scrub_metadata": str(scrub),
        },
    )
    assert response.status_code == 200, response.text
    assert response.headers["X-Redacted-Count"] == "7"
    assert response.headers["X-Verified-Unrecoverable"] == "true"
    assert response.headers["X-Metadata-Scrubbed"] == str(scrub).lower()
    download = client.get(response.json()["download_url"])
    with pymupdf.open(stream=download.content, filetype="pdf") as doc:
        assert doc[0].get_text().split() == ["/", "/", "public"]
        assert bool(doc.metadata.get("author")) != scrub
        assert bool(doc.get_xml_metadata()) != scrub
        assert bool(list(doc[0].annots())) != scrub
        assert bool(doc.embfile_names()) != scrub


@pytest.mark.parametrize(
    ("options", "code"),
    [
        ({}, "invalid_request"),
        ({"presets": "unknown"}, "invalid_request"),
        ({"terms": "absent", "scrub_metadata": "false"}, "no_matches"),
    ],
)
def test_invalid_request(client, options, code):
    response = client.post(
        "/api/redact-pdf", files={"file": ("in.pdf", sample())}, data=options
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == code


def test_scrub_without_hits(client):
    response = client.post(
        "/api/redact-pdf",
        files={"file": ("in.pdf", sample())},
        data={"terms": "absent"},
    )
    assert response.status_code == 200
    assert response.headers["X-Redacted-Count"] == "0"


def test_scrubbing_honors_existing_redactions(client):
    with pymupdf.open() as doc:
        page = doc.new_page()
        page.insert_text((40, 50), "already marked")
        page.add_redact_annot(page.search_for("already marked")[0], fill=(0, 0, 0))
        response = client.post(
            "/api/redact-pdf",
            files={"file": ("in.pdf", doc.tobytes())},
            data={"terms": "absent"},
        )
    assert response.status_code == 200, response.text
    with pymupdf.open(
        stream=client.get(response.json()["download_url"]).content
    ) as saved:
        assert not saved[0].get_text().strip()


def test_overlapping_wrapped_and_literal_phrases_on_every_page(client):
    with pymupdf.open() as doc:
        for _ in range(2):
            page = doc.new_page()
            page.insert_text((40, 50), "Project\nLumen\nbanana\n[A+B] public")
        response = client.post(
            "/api/redact-pdf",
            files={"file": ("in.pdf", doc.tobytes())},
            data={"terms": "project lumen,ana\n[A+B]"},
        )
    assert response.status_code == 200, response.text
    assert response.headers["X-Redacted-Count"] == "8"
    with pymupdf.open(
        stream=client.get(response.json()["download_url"]).content
    ) as saved:
        assert [page.get_text().split() for page in saved] == [["b", "public"]] * 2


def test_original_image_pixels_and_overlapping_vector_are_removed(client):
    with pymupdf.open() as doc:
        page = doc.new_page(width=200, height=200)
        image = pymupdf.Pixmap(pymupdf.csRGB, (0, 0, 200, 200), False)
        image.clear_with(80)
        page.insert_image(page.rect, pixmap=image)
        page.draw_line((40, 75), (130, 75), color=(1, 0, 0))
        page.insert_text((40, 80), "secret")
        response = client.post(
            "/api/redact-pdf",
            files={"file": ("in.pdf", doc.tobytes())},
            data={"terms": "secret"},
        )
    assert response.status_code == 200, response.text
    with pymupdf.open(
        stream=client.get(response.json()["download_url"]).content
    ) as saved:
        page = saved[0]
        assert page.get_pixmap().pixel(50, 75) == (0, 0, 0)
        for xref, *_ in page.get_images():
            underlying = pymupdf.Pixmap(saved, xref)
            assert underlying.pixel(50, 75) != underlying.pixel(10, 10)
        assert not any(path["color"] == (1, 0, 0) for path in page.get_drawings())


def test_verification_failure_withholds_download_and_cleans_up(
    client, storage_dir, monkeypatch
):
    monkeypatch.setattr(pymupdf.Page, "apply_redactions", lambda *args, **kwargs: False)
    response = client.post(
        "/api/redact-pdf",
        files={"file": ("in.pdf", sample())},
        data={"terms": "private phrase", "scrub_metadata": "false"},
    )
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "processing_failed"
    assert "X-Verified-Unrecoverable" not in response.headers
    assert not any(path.is_file() for path in storage_dir.rglob("*"))


def test_audit_rejects_a_partially_removed_phrase(client, monkeypatch):
    add_annotation = pymupdf.Page.add_redact_annot

    def partial_annotation(page, rect, **kwargs):
        fragment = pymupdf.Rect(rect)
        fragment.x1 = fragment.x0 + fragment.width / 3
        return add_annotation(page, fragment, **kwargs)

    monkeypatch.setattr(pymupdf.Page, "add_redact_annot", partial_annotation)
    response = client.post(
        "/api/redact-pdf",
        files={"file": ("private.pdf", sample())},
        data={"terms": "private phrase"},
    )
    assert response.status_code == 500
    assert "download_url" not in response.json()
    assert "X-Verified-Unrecoverable" not in response.headers
