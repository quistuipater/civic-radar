import logging
import signal
from pathlib import Path

from sqlalchemy.orm import Session

from app.models import Document, DocumentChunk
from app.parsing.extract import chunk_pages, extract_structured_fields, parse_file

logger = logging.getLogger(__name__)

# Wall-clock safety net for pathological inputs (board packets can run into the
# thousands of pages, where pdfminer/pdfplumber's per-page overhead adds up
# regardless of the OCR page cap) -- without this, one such document could
# occupy run_parsing_batch()'s single worker thread indefinitely, since a
# document stuck mid-parse is never committed and gets retried every tick.
# Only safe to use here: parse_document() is only ever called from the
# worker's main thread (see app/worker.py), and signal.alarm requires that.
PARSE_TIMEOUT_SECONDS = 120


class _ParseTimeout(Exception):
    pass


def _raise_timeout(signum, frame):
    raise _ParseTimeout(f"parsing exceeded {PARSE_TIMEOUT_SECONDS}s time budget (unusually large/complex document)")


def parse_document(db: Session, document: Document) -> None:
    if document.parser_status == "parsed":
        return

    path = Path(document.archive_path)
    previous_handler = signal.signal(signal.SIGALRM, _raise_timeout)
    signal.alarm(PARSE_TIMEOUT_SECONDS)
    try:
        parsed = parse_file(path, document.mime_type)
    except Exception as exc:  # noqa: BLE001 - parser failures must not crash the pipeline
        document.parser_status = "failed"
        document.parser_error = str(exc)[:2000]
        db.commit()
        logger.warning("parsing failed for document %s: %s", document.id, exc)
        return
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous_handler)

    # Postgres TEXT/VARCHAR columns reject embedded NUL bytes outright (a real
    # DataError, not a warning) -- some PDFs (seen live in a 900+ page Santa
    # Cruz budget packet) extract with stray \x00 bytes from the source
    # encoding. Stripped here, once, before anything downstream (chunk rows,
    # the .txt sidecar, structured-field regexes) can see them, rather than
    # letting the failure surface deep inside a bulk chunk INSERT.
    parsed.full_text = parsed.full_text.replace("\x00", "")
    for page in parsed.pages:
        page.text = page.text.replace("\x00", "")

    text_path = path.with_suffix(path.suffix + ".txt")
    text_path.write_text(parsed.full_text)
    document.extracted_text_path = str(text_path)

    db.query(DocumentChunk).filter(DocumentChunk.document_id == document.id).delete()
    for chunk in chunk_pages(parsed):
        db.add(DocumentChunk(document_id=document.id, **chunk))

    fields = extract_structured_fields(parsed.full_text)
    for key, value in fields.items():
        if getattr(document, key, None) is None:
            setattr(document, key, value)

    document.parser_status = "parsed"
    document.parser_error = None
    db.commit()
