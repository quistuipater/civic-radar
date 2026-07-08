"""Turn archived HTML/PDF files into searchable text and chunks (prd.md 9.4).

PDF text is extracted page by page so we can keep document-to-page mapping.
Structured fields (ordinance/resolution/project numbers, APNs) are pulled with
regexes — a first-pass heuristic, not a substitute for the AI extraction layer.
"""

import logging
import re
from dataclasses import dataclass
from pathlib import Path

import pdfplumber
import pytesseract
from bs4 import BeautifulSoup
from pdf2image import convert_from_path

logger = logging.getLogger(__name__)

OCR_DPI = 200
# Compiled board packets can run into the thousands of pages; without a cap, a
# single such document could pin OCR (subprocess rasterization + Tesseract per
# page) for hours and hold the memory that entails the whole time. Text-native
# pages are unaffected -- this only limits how many *non-text* pages we'll
# attempt to recover per document.
MAX_OCR_PAGES_PER_DOCUMENT = 40


@dataclass
class ParsedPage:
    page_number: int
    text: str


@dataclass
class ParsedDocument:
    full_text: str
    pages: list[ParsedPage]


def parse_file(path: Path, mime_type: str | None) -> ParsedDocument:
    suffix = path.suffix.lower()
    if suffix == ".pdf" or mime_type == "application/pdf":
        return _parse_pdf(path)
    if suffix in (".html", ".htm") or mime_type == "text/html":
        return _parse_html(path)
    if suffix in (".txt", ".csv"):
        text = path.read_text(errors="ignore")
        return ParsedDocument(full_text=text, pages=[ParsedPage(1, text)])
    raise ValueError(f"unsupported file type: {path} ({mime_type})")


def _parse_pdf(path: Path) -> ParsedDocument:
    pages: list[ParsedPage] = []
    ocr_pages_used = 0
    ocr_cap_logged = False
    with pdfplumber.open(str(path)) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            if not text.strip():
                if ocr_pages_used < MAX_OCR_PAGES_PER_DOCUMENT:
                    text = _ocr_page(path, i)
                    ocr_pages_used += 1
                elif not ocr_cap_logged:
                    logger.warning(
                        "OCR page cap (%d) reached for %s; remaining non-text pages left blank",
                        MAX_OCR_PAGES_PER_DOCUMENT,
                        path,
                    )
                    ocr_cap_logged = True
            pages.append(ParsedPage(page_number=i, text=text))
            # pdfplumber caches each page's parsed objects (chars, layout, etc.)
            # on the Page instance for the life of `pdf`; without releasing it,
            # a many-thousand-page document accumulates that cache for every
            # page simultaneously and can OOM the process (seen live on a
            # 6,102-page board packet). Safe to drop once we have the text.
            page.close()
    full_text = "\n\n".join(p.text for p in pages)
    if not full_text.strip():
        raise ValueError("no extractable text, even after OCR (image quality too low, or OCR unavailable)")
    return ParsedDocument(full_text=full_text, pages=pages)


def _ocr_page(path: Path, page_number: int) -> str:
    """Fallback for pages pdfplumber found no embedded text on (scanned/image-only
    pages, e.g. some closed-session minutes) -- rasterize just that page and run
    Tesseract over it. Degrades to empty text (logged) rather than raising, so one
    bad page doesn't fail parsing for a document whose other pages have real text.
    """
    try:
        images = convert_from_path(str(path), first_page=page_number, last_page=page_number, dpi=OCR_DPI)
    except Exception as exc:  # noqa: BLE001 - poppler/OCR failures must not crash the pipeline
        logger.warning("OCR rasterization failed for %s page %d: %s", path, page_number, exc)
        return ""
    if not images:
        return ""
    try:
        return pytesseract.image_to_string(images[0])
    except Exception as exc:  # noqa: BLE001
        logger.warning("OCR failed for %s page %d: %s", path, page_number, exc)
        return ""


def _parse_html(path: Path) -> ParsedDocument:
    soup = BeautifulSoup(path.read_text(errors="ignore"), "lxml")
    for tag in soup(["script", "style"]):
        tag.decompose()
    text = soup.get_text("\n", strip=True)
    return ParsedDocument(full_text=text, pages=[ParsedPage(1, text)])


def chunk_pages(parsed: ParsedDocument, max_chars: int = 3000) -> list[dict]:
    """Yield chunk dicts: {chunk_index, page_start, page_end, text, token_count}."""
    chunks: list[dict] = []
    buf = ""
    page_start = None
    for page in parsed.pages:
        if page_start is None:
            page_start = page.page_number
        candidate = f"{buf}\n\n{page.text}" if buf else page.text
        if len(candidate) > max_chars and buf:
            chunks.append(_make_chunk(len(chunks), page_start, page.page_number - 1, buf))
            buf = page.text
            page_start = page.page_number
        else:
            buf = candidate
    if buf.strip():
        chunks.append(_make_chunk(len(chunks), page_start or 1, parsed.pages[-1].page_number if parsed.pages else 1, buf))
    return chunks


def _make_chunk(index: int, page_start: int, page_end: int, text: str) -> dict:
    return {
        "chunk_index": index,
        "page_start": page_start,
        "page_end": page_end,
        "text": text.strip(),
        "token_count": max(1, len(text) // 4),
    }


ORDINANCE_RE = re.compile(r"Ordinance\s+No\.?\s*([A-Z0-9\-]{2,20})", re.IGNORECASE)
RESOLUTION_RE = re.compile(r"Resolution\s+No\.?\s*([A-Z0-9\-]{2,20})", re.IGNORECASE)
PROJECT_RE = re.compile(r"(?:Project|Case)\s*(?:No\.?|#)\s*([A-Z]{0,6}-?\d{2,6}-?\d{0,6})", re.IGNORECASE)
APN_RE = re.compile(r"APN[:\s#]*([\d]{3}-?[\d]{1,3}-?[\d]{1,3})", re.IGNORECASE)


def extract_structured_fields(text: str) -> dict:
    fields = {}
    for key, pattern in (
        ("ordinance_number", ORDINANCE_RE),
        ("resolution_number", RESOLUTION_RE),
        ("project_number", PROJECT_RE),
        ("apn", APN_RE),
    ):
        match = pattern.search(text)
        if match:
            fields[key] = match.group(1).strip()
    return fields
