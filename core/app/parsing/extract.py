"""Turn archived HTML/PDF files into searchable text and chunks (prd.md 9.4).

PDF text is extracted page by page so we can keep document-to-page mapping.
Structured fields (ordinance/resolution/project numbers, APNs, hearing dates/
comment deadlines) are pulled with regexes — a first-pass heuristic, not a
substitute for the AI extraction layer.
"""

import base64
import io
import logging
import re
from dataclasses import dataclass
from pathlib import Path

import pdfplumber
import pytesseract
from bs4 import BeautifulSoup
from dateutil import parser as dateutil_parser
from pdf2image import convert_from_path

from app.ai import ollama_client
from app.config import settings

logger = logging.getLogger(__name__)

OCR_DPI = 200
# See _ocr_page's docstring for why the vision fallback is tried
# unconditionally on these already-rare pages rather than gated behind
# Tesseract's own (confirmed live 2026-08-18 to be unreliable here)
# confidence score.
#
# Deliberately well under parsing/service.py's PARSE_TIMEOUT_SECONDS (a
# wall-clock cap on the *whole* parse_document() call, bumped alongside this
# constant -- see that module): confirmed live 2026-08-18 that using
# generate_vision's own 120s default here let one slow vision call consume
# the entire outer budget by itself, leaving no time for the Tesseract
# fallback to even run -- the document got killed and marked "failed"
# instead of degrading gracefully to Tesseract's output. A single real
# vision call on one page was observed taking ~63s under light load and
# timing out at 90s under GPU contention from concurrent Ollama calls
# (confirmed live 2026-08-18), so this needs enough room to actually succeed
# most of the time while still leaving headroom under the outer cap for the
# Tesseract fallback.
VISION_OCR_TIMEOUT_SECONDS = 150.0
VISION_OCR_PROMPT = (
    "Transcribe all text visible on this scanned document page, including "
    "handwritten text. Output only the transcribed text in plain text form, "
    "preserving line breaks and the page's layout as closely as reasonably "
    "possible. Do not add commentary, labels, or markdown formatting -- "
    "output only what is written on the page."
)
# Compiled board packets can run into the thousands of pages; without a cap, a
# single such document could pin OCR (subprocess rasterization + Tesseract per
# page) for hours and hold the memory that entails the whole time. Text-native
# pages are unaffected -- this only limits how many *non-text* pages we'll
# attempt to recover per document.
MAX_OCR_PAGES_PER_DOCUMENT = 40
# Separate, much tighter cap on the vision-model attempt specifically: real
# large board packets can have dozens of scanned/non-text pages, and at
# VISION_OCR_TIMEOUT_SECONDS (150s) each, trying vision on all of them under
# MAX_OCR_PAGES_PER_DOCUMENT blows past PARSE_TIMEOUT_SECONDS regardless of
# how high that's raised -- confirmed live 2026-08-22, several Ventura/Santa
# Cruz packets failed every retry this way. Past this many vision attempts
# per document, remaining OCR pages go straight to Tesseract (still counted
# against MAX_OCR_PAGES_PER_DOCUMENT above) so total runtime stays bounded
# regardless of how many scanned pages a packet has.
MAX_VISION_OCR_PAGES_PER_DOCUMENT = 3


@dataclass
class ParsedPage:
    page_number: int
    text: str


@dataclass
class ParsedDocument:
    full_text: str
    pages: list[ParsedPage]
    # True if any page's text came from the vision-OCR fallback. Confirmed
    # live 2026-08-18 that this text can be fluently, confidently wrong (a
    # handwritten candidate's name misread as a plausible-looking different
    # name) in ways Tesseract's obviously-garbled output never was -- so
    # parse_document() uses this to flag the document for mandatory human
    # review rather than trusting it like embedded/Tesseract-derived text.
    used_vision_ocr: bool = False


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
    vision_pages_used = 0
    ocr_cap_logged = False
    used_vision_ocr = False
    with pdfplumber.open(str(path)) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            if not text.strip():
                if ocr_pages_used < MAX_OCR_PAGES_PER_DOCUMENT:
                    allow_vision = vision_pages_used < MAX_VISION_OCR_PAGES_PER_DOCUMENT
                    text, page_used_vision = _ocr_page(path, i, allow_vision=allow_vision)
                    used_vision_ocr = used_vision_ocr or page_used_vision
                    ocr_pages_used += 1
                    if page_used_vision:
                        vision_pages_used += 1
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
    return ParsedDocument(full_text=full_text, pages=pages, used_vision_ocr=used_vision_ocr)


def _ocr_page(path: Path, page_number: int, allow_vision: bool = True) -> tuple[str, bool]:
    """Fallback for pages pdfplumber found no embedded text on (scanned/image-only
    pages, e.g. some closed-session minutes) -- rasterize just that page and run
    OCR over it. Degrades to empty text (logged) rather than raising, so one bad
    page doesn't fail parsing for a document whose other pages have real text.

    Tries the vision model first, not Tesseract's own confidence as a gate --
    tried that, and confirmed live 2026-08-18 that Tesseract scored 88%
    confidence on a handwritten page it read completely wrong ("Director"
    as "Priveerbor"), so its self-reported confidence doesn't distinguish
    "read this correctly" from "pattern-matched glyph shapes confidently".
    Only pages reaching this function are already the minority (pdfplumber
    found zero embedded text on them, capped at MAX_OCR_PAGES_PER_DOCUMENT),
    so the added vision-model cost is bounded per-page -- but `allow_vision`
    (set by the caller once MAX_VISION_OCR_PAGES_PER_DOCUMENT is hit) skips
    straight to Tesseract, since a packet can have far more OCR pages than
    the whole document's time budget can afford one 150s vision call each.
    Falls back to Tesseract's output if the vision call fails/is
    unavailable/times out/was skipped.

    Returns (text, used_vision_ocr) -- the caller propagates used_vision_ocr
    up to ParsedDocument so parse_document() can flag the document for
    mandatory human review: vision-OCR text has also been confirmed live to
    be fluently, confidently *wrong* in ways Tesseract's obviously-garbled
    output never was (a handwritten candidate's name misread as a different,
    equally plausible-looking real name) -- worse to silently trust than
    Tesseract's garbage, which nobody would mistake for a real value.
    """
    try:
        images = convert_from_path(str(path), first_page=page_number, last_page=page_number, dpi=OCR_DPI)
    except Exception as exc:  # noqa: BLE001 - poppler/OCR failures must not crash the pipeline
        logger.warning("OCR rasterization failed for %s page %d: %s", path, page_number, exc)
        return "", False
    if not images:
        return "", False
    image = images[0]

    if allow_vision:
        vision_text = _vision_ocr_page(image)
        if vision_text:
            return vision_text, True

    try:
        return pytesseract.image_to_string(image), False
    except Exception as exc:  # noqa: BLE001
        logger.warning("OCR failed for %s page %d: %s", path, page_number, exc)
        return "", False


def _vision_ocr_page(image) -> str | None:
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    image_b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    text, error = ollama_client.generate_vision(
        settings.ollama_vision_model, VISION_OCR_PROMPT, image_b64, timeout=VISION_OCR_TIMEOUT_SECONDS
    )
    if error:
        logger.warning("vision OCR fallback failed: %s", error)
    return text


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

# A first-pass heuristic, same caveat as the identifier regexes above: real
# civic-notice phrasing for hearing dates/comment deadlines varies a lot more
# than a project number ever does, so this catches common phrasings rather
# than every one -- documents where it misses just keep comment_deadline/
# public_hearing_date at None, same as if nothing here existed yet.
DATE_PATTERN = r"[A-Z][a-z]+\.?\s+\d{1,2},?\s+\d{4}|\d{1,2}/\d{1,2}/\d{4}"
PUBLIC_HEARING_RE = re.compile(
    rf"(?:public\s+)?hearing\s+(?:will\s+be\s+held|is\s+scheduled(?:\s+for)?|will\s+take\s+place)\s*(?:on\s+)?({DATE_PATTERN})",
    re.IGNORECASE,
)
COMMENT_DEADLINE_RE = re.compile(
    rf"comments?[^.\n]{{0,80}}?(?:must\s+be\s+received\s+by|no\s+later\s+than|due\s+by|deadline\s+is|accepted\s+until|will\s+be\s+accepted\s+until)\s+({DATE_PATTERN})",
    re.IGNORECASE,
)
# Same idea, reversed word order ("deadline ... for comments ... is <date>"
# rather than "comments ... by <date>") -- civic notices use both.
COMMENT_DEADLINE_RE_ALT = re.compile(
    rf"deadline[^.\n]{{0,40}}?comments?[^.\n]{{0,20}}?(?:is|of|falls\s+on)\s+({DATE_PATTERN})",
    re.IGNORECASE,
)


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

    for key, patterns in (
        ("public_hearing_date", (PUBLIC_HEARING_RE,)),
        ("comment_deadline", (COMMENT_DEADLINE_RE, COMMENT_DEADLINE_RE_ALT)),
    ):
        for pattern in patterns:
            match = pattern.search(text)
            if match:
                parsed_date = _parse_date_fuzzy(match.group(1))
                if parsed_date:
                    fields[key] = parsed_date
                    break
    return fields


def _parse_date_fuzzy(date_str: str):
    try:
        return dateutil_parser.parse(date_str).date()
    except (ValueError, OverflowError):
        return None
