"""Tests for document text extraction. The PDF path is tested against a
mocked pdfplumber rather than a real PDF file: the actual thing worth
protecting here isn't "does pdfplumber work" (a third-party library), it's
our own logic around it -- the OCR fallback trigger, the per-document OCR
page cap, and page.close() being called for every single page regardless of
outcome (the exact fix for a live OOM crash on a 6,102-page board packet,
where pdfplumber's per-page object cache accumulated for the life of the
`pdf` object). Mocking gives precise, fast control over all of that; a real
PDF fixture couldn't exercise the OCR-cap or many-thousands-of-pages cases at
all practically.
"""

from pathlib import Path

import app.parsing.extract as extract_module
from app.parsing.extract import (
    ParsedDocument,
    ParsedPage,
    chunk_pages,
    extract_structured_fields,
    parse_file,
)


class FakePage:
    def __init__(self, text):
        self._text = text
        self.closed = False

    def extract_text(self):
        return self._text

    def close(self):
        self.closed = True


class FakePdf:
    def __init__(self, pages):
        self.pages = pages

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def install_fake_pdfplumber(monkeypatch, pages):
    fake_pdf = FakePdf(pages)
    monkeypatch.setattr(extract_module.pdfplumber, "open", lambda path: fake_pdf)
    return fake_pdf


class TestParseFileDispatch:
    def test_dispatches_pdf_by_extension(self, tmp_path, monkeypatch):
        called = {}

        def fake_parse_pdf(path):
            called["path"] = path
            return ParsedDocument(full_text="ok", pages=[ParsedPage(1, "ok")])

        monkeypatch.setattr(extract_module, "_parse_pdf", fake_parse_pdf)
        path = tmp_path / "doc.pdf"
        path.write_bytes(b"whatever")

        result = parse_file(path, None)

        assert result.full_text == "ok"
        assert called["path"] == path

    def test_dispatches_pdf_by_mime_type_even_with_wrong_extension(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            extract_module, "_parse_pdf", lambda path: ParsedDocument(full_text="ok", pages=[ParsedPage(1, "ok")])
        )
        path = tmp_path / "doc.bin"
        path.write_bytes(b"whatever")

        result = parse_file(path, "application/pdf")

        assert result.full_text == "ok"

    def test_dispatches_html_by_extension(self, tmp_path):
        path = tmp_path / "page.html"
        path.write_text("<html><body><p>Hello <script>ignored()</script></p></body></html>")

        result = parse_file(path, None)

        assert "Hello" in result.full_text
        assert "ignored" not in result.full_text

    def test_dispatches_txt_and_csv_as_plain_text(self, tmp_path):
        path = tmp_path / "notes.txt"
        path.write_text("plain text content")

        result = parse_file(path, None)

        assert result.full_text == "plain text content"
        assert result.pages == [ParsedPage(1, "plain text content")]

    def test_raises_for_unsupported_extension(self, tmp_path):
        path = tmp_path / "archive.zip"
        path.write_bytes(b"PK\x03\x04")

        try:
            parse_file(path, None)
            assert False, "expected ValueError"
        except ValueError as exc:
            assert "unsupported file type" in str(exc)


class TestParsePdf:
    def test_text_native_pages_do_not_trigger_ocr(self, tmp_path, monkeypatch):
        install_fake_pdfplumber(monkeypatch, [FakePage("Real embedded text")])
        ocr_calls = []
        monkeypatch.setattr(extract_module, "_ocr_page", lambda path, n: ocr_calls.append(n) or "")

        result = extract_module._parse_pdf(tmp_path / "doc.pdf")

        assert result.full_text == "Real embedded text"
        assert ocr_calls == []

    def test_page_with_no_embedded_text_falls_back_to_ocr(self, tmp_path, monkeypatch):
        install_fake_pdfplumber(monkeypatch, [FakePage("")])
        monkeypatch.setattr(extract_module, "_ocr_page", lambda path, n: "OCR recovered text")

        result = extract_module._parse_pdf(tmp_path / "doc.pdf")

        assert "OCR recovered text" in result.full_text

    def test_every_page_is_closed_regardless_of_text_or_ocr_outcome(self, tmp_path, monkeypatch):
        # The exact fix for a live OOM crash: pdfplumber caches each page's
        # parsed objects on the Page instance for the life of `pdf`, so
        # page.close() must run for every page even when OCR is involved.
        pages = [FakePage("text"), FakePage(""), FakePage("more text")]
        install_fake_pdfplumber(monkeypatch, pages)
        monkeypatch.setattr(extract_module, "_ocr_page", lambda path, n: "")

        extract_module._parse_pdf(tmp_path / "doc.pdf")

        assert all(p.closed for p in pages)

    def test_ocr_page_cap_leaves_remaining_non_text_pages_blank(self, tmp_path, monkeypatch):
        pages = [FakePage("") for _ in range(extract_module.MAX_OCR_PAGES_PER_DOCUMENT + 5)]
        install_fake_pdfplumber(monkeypatch, pages)
        ocr_calls = []
        monkeypatch.setattr(extract_module, "_ocr_page", lambda path, n: ocr_calls.append(n) or f"ocr-{n}")

        result = extract_module._parse_pdf(tmp_path / "doc.pdf")

        assert len(ocr_calls) == extract_module.MAX_OCR_PAGES_PER_DOCUMENT
        # pages beyond the cap have no text at all (not even attempted)
        assert result.pages[-1].text == ""

    def test_raises_when_no_text_recoverable_even_after_ocr(self, tmp_path, monkeypatch):
        install_fake_pdfplumber(monkeypatch, [FakePage("")])
        monkeypatch.setattr(extract_module, "_ocr_page", lambda path, n: "")

        try:
            extract_module._parse_pdf(tmp_path / "doc.pdf")
            assert False, "expected ValueError"
        except ValueError as exc:
            assert "no extractable text" in str(exc)

    def test_ocr_rasterization_failure_degrades_to_empty_text_not_a_crash(self, monkeypatch, tmp_path):
        def raise_error(*a, **k):
            raise RuntimeError("poppler not found")

        monkeypatch.setattr(extract_module, "convert_from_path", raise_error)

        assert extract_module._ocr_page(tmp_path / "doc.pdf", 1) == ""

    def test_ocr_with_no_images_returned_yields_empty_text(self, monkeypatch, tmp_path):
        monkeypatch.setattr(extract_module, "convert_from_path", lambda *a, **k: [])

        assert extract_module._ocr_page(tmp_path / "doc.pdf", 1) == ""

    def test_tesseract_failure_degrades_to_empty_text_not_a_crash(self, monkeypatch, tmp_path):
        monkeypatch.setattr(extract_module, "convert_from_path", lambda *a, **k: ["fake-image"])

        def raise_error(image):
            raise RuntimeError("tesseract not found")

        monkeypatch.setattr(extract_module.pytesseract, "image_to_string", raise_error)

        assert extract_module._ocr_page(tmp_path / "doc.pdf", 1) == ""


class TestChunkPages:
    def test_single_short_page_is_one_chunk(self):
        parsed = ParsedDocument(full_text="short text", pages=[ParsedPage(1, "short text")])
        chunks = chunk_pages(parsed)
        assert len(chunks) == 1
        assert chunks[0]["page_start"] == 1
        assert chunks[0]["page_end"] == 1
        assert chunks[0]["text"] == "short text"

    def test_pages_are_merged_into_one_chunk_until_max_chars_exceeded(self):
        pages = [ParsedPage(1, "a" * 100), ParsedPage(2, "b" * 100)]
        parsed = ParsedDocument(full_text="", pages=pages)
        chunks = chunk_pages(parsed, max_chars=1000)
        assert len(chunks) == 1
        assert chunks[0]["page_start"] == 1
        assert chunks[0]["page_end"] == 2

    def test_exceeding_max_chars_starts_a_new_chunk(self):
        pages = [ParsedPage(1, "a" * 100), ParsedPage(2, "b" * 100), ParsedPage(3, "c" * 100)]
        parsed = ParsedDocument(full_text="", pages=pages)
        chunks = chunk_pages(parsed, max_chars=150)
        assert len(chunks) >= 2
        assert chunks[0]["page_end"] < chunks[-1]["page_start"] or len(chunks) == 2

    def test_chunk_index_increments_sequentially(self):
        pages = [ParsedPage(i, "x" * 100) for i in range(1, 5)]
        parsed = ParsedDocument(full_text="", pages=pages)
        chunks = chunk_pages(parsed, max_chars=150)
        assert [c["chunk_index"] for c in chunks] == list(range(len(chunks)))

    def test_empty_pages_list_yields_no_chunks(self):
        parsed = ParsedDocument(full_text="", pages=[])
        assert chunk_pages(parsed) == []

    def test_whitespace_only_text_yields_no_chunks(self):
        parsed = ParsedDocument(full_text="   ", pages=[ParsedPage(1, "   ")])
        assert chunk_pages(parsed) == []

    def test_token_count_is_roughly_a_quarter_of_char_count(self):
        parsed = ParsedDocument(full_text="", pages=[ParsedPage(1, "x" * 40)])
        chunks = chunk_pages(parsed)
        assert chunks[0]["token_count"] == 10

    def test_token_count_is_never_zero_even_for_tiny_text(self):
        parsed = ParsedDocument(full_text="", pages=[ParsedPage(1, "hi")])
        chunks = chunk_pages(parsed)
        assert chunks[0]["token_count"] >= 1


class TestExtractStructuredFields:
    def test_extracts_ordinance_number(self):
        fields = extract_structured_fields("The council adopted Ordinance No. 2026-05 on first reading.")
        assert fields["ordinance_number"] == "2026-05"

    def test_extracts_resolution_number(self):
        fields = extract_structured_fields("Approved per Resolution No. 26-112.")
        assert fields["resolution_number"] == "26-112"

    def test_extracts_project_number(self):
        fields = extract_structured_fields("Case No. PL2026-0042 was reviewed by staff.")
        assert fields["project_number"] == "PL2026-0042"

    def test_extracts_apn(self):
        fields = extract_structured_fields("APN: 123-456-789 is the subject parcel.")
        assert fields["apn"] == "123-456-789"

    def test_matching_is_case_insensitive(self):
        fields = extract_structured_fields("ordinance no. 2026-05")
        assert fields["ordinance_number"] == "2026-05"

    def test_returns_empty_dict_when_nothing_matches(self):
        assert extract_structured_fields("just some ordinary text with no identifiers") == {}

    def test_extracts_multiple_fields_from_the_same_text(self):
        fields = extract_structured_fields("Ordinance No. 2026-05 relates to Case No. PL2026-0042.")
        assert fields["ordinance_number"] == "2026-05"
        assert fields["project_number"] == "PL2026-0042"
