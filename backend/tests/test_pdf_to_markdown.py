import pymupdf
import pytest


def post(client, doc, **options):
    return client.post(
        "/api/pdf-to-markdown",
        files={"file": ("report.pdf", doc.tobytes())},
        data=options,
    )


@pytest.mark.parametrize("markers", [True, False])
def test_layout_and_download(client, markers):
    with pymupdf.open() as doc:
        for n in (1, 2):
            page = doc.new_page()
            page.insert_text((40, 30), "Recurring header")
            page.insert_text((40, 140), "Report", fontsize=24)
            page.insert_text((40, 170), "Section", fontsize=17)
            page.insert_text((40, 205), "Details", fontsize=14)
            for y, left, right in [
                (260, "Left first", "Right first"),
                (290, "Left second", "Right second"),
            ]:
                page.insert_text((40, y), left, fontsize=10)
                page.insert_text((330, y), right, fontsize=10)
            page.insert_text((40, 360), "1. First item", fontsize=10)
            page.insert_text((40, 810), f"Page {n}")
        response = post(client, doc, include_page_markers=str(markers))
    assert response.status_code == 200, response.text
    data = response.json()
    md = data["markdown"]
    assert "# Report" in md and "## Section" in md and "### Details" in md
    assert md.index("Left second") < md.index("Right first")
    assert "1. First item" in md and "Recurring header" not in md
    assert ("<!-- Page 2 -->" in md) == markers
    assert response.headers["X-Page-Count"] == "2"
    assert int(response.headers["X-Word-Count"]) == data["word_count"] > 0
    assert int(response.headers["X-Estimated-Tokens"]) == data["estimated_tokens"] > 0
    download = client.get(data["download_url"])
    assert download.text == md
    assert download.headers["content-type"].startswith("text/markdown")


def test_table(client):
    with pymupdf.open() as doc:
        p = doc.new_page()
        for x in (50, 140, 230):
            p.draw_line((x, 100), (x, 160))
        for y in (100, 130, 160):
            p.draw_line((50, y), (230, y))
        for x, y, value in [
            (55, 120, "Name"),
            (145, 120, "Score"),
            (55, 150, "Alice"),
            (145, 150, "12"),
        ]:
            p.insert_text((x, y), value)
        response = post(client, doc)
    md = response.json()["markdown"]
    assert "| Name | Score |\n| --- | --- |\n| Alice | 12 |" in md
    assert md.count("Alice") == 1
    assert md.startswith("<!-- Page 1 -->")


def test_image_only(client):
    with pymupdf.open() as doc:
        page = doc.new_page()
        pix = pymupdf.Pixmap(pymupdf.csRGB, (0, 0, 8, 8), False)
        pix.clear_with(255)
        page.insert_image(page.rect, pixmap=pix)
        response = post(client, doc)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "no_content"


def test_wide_heading_then_columns_and_list(client):
    with pymupdf.open() as doc:
        page = doc.new_page()
        page.insert_text(
            (40, 95), "A full-width heading over both columns", fontsize=22
        )
        for y, left, right in [
            (130, "- First item", "1) Read this later"),
            (150, "- Second item", "2) Last item"),
        ]:
            page.insert_text((40, y), left)
            page.insert_text((300, y), right)
        response = post(client, doc, include_page_markers="false")
    assert response.status_code == 200, response.text
    assert response.json()["markdown"].splitlines() == [
        "# A full-width heading over both columns",
        "",
        "- First item",
        "- Second item",
        "1. Read this later",
        "2. Last item",
    ]
