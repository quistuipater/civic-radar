"""Ties together: fetch a source -> archive raw material -> discover linked
documents -> archive + record each one. One call handles one source's polling
cycle end to end (prd.md 9.2, 9.3, 15.2).
"""

import logging
import time
from datetime import date, datetime, timezone

import httpx
from sqlalchemy.orm import Session

from app.archive import archive_dir_for, now_utc, sha256_hex, write_archive_file, write_metadata
from app.ingestion.connectors import (
    boston_public_notices,
    civicplus_agenda_center,
    generic,
    netfile_rss,
    ocpf,
    primegov,
    static_page,
)
from app.ingestion.connectors.base import DiscoveredDocument
from app.ingestion.http_client import fetch_url
from app.models import Document, Fetch, Meeting, Source

logger = logging.getLogger(__name__)

CONNECTORS = {
    "civicplus_agenda_center": civicplus_agenda_center.discover,
    "generic": generic.discover,
    "primegov": primegov.discover,
    "netfile_rss": netfile_rss.discover,
    "ocpf": ocpf.discover,
    "boston_public_notices": boston_public_notices.discover,
    "static_page": static_page.discover,
}

EXT_BY_CONTENT_TYPE = {
    "application/pdf": ".pdf",
    "application/msword": ".doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "text/csv": ".csv",
    "text/html": ".html",
}


def ingest_source(db: Session, source: Source) -> Fetch:
    started = time.monotonic()
    fetch = Fetch(source_id=source.id, status="pending")
    db.add(fetch)

    try:
        response = fetch_url(source.url)
    except httpx.HTTPError as exc:
        fetch.status = "error"
        fetch.error_message = str(exc)[:2000]
        fetch.duration_ms = int((time.monotonic() - started) * 1000)
        fetch.validation_status = "error"
        fetch.validation_message = "HTTP fetch failed"
        source.last_error = fetch.error_message
        source.consecutive_failures += 1
        source.last_fetched_at = now_utc()
        db.commit()
        logger.warning("fetch failed for source %s: %s", source.name, exc)
        return fetch

    body = response.content
    page_hash = sha256_hex(body)
    directory = archive_dir_for(source.jurisdiction, source.body, now_utc())

    fetch.http_status = response.status_code
    fetch.content_hash = page_hash
    fetch.status = "ok"

    snapshot_path = write_archive_file(directory, f"source_snapshot_{page_hash[:12]}.html", body)
    fetch.archive_path = str(snapshot_path)

    # Ordinary sources link out to PDFs to harvest, so the page itself is
    # just a change-detection snapshot (parsing it would be pure waste --
    # see _upsert_document). A "static_reference_page" source is the
    # opposite: the page's own prose IS the payload (e.g. a "Form of
    # Government" page stating who reports to whom), so it needs to flow
    # through parsing/AI extraction like a real document.
    is_static_reference_page = source.source_type == "static_reference_page"
    snapshot_doc, snapshot_is_new = _upsert_document(
        db,
        source=source,
        fetch=fetch,
        archive_path=snapshot_path,
        content=body,
        content_hash=page_hash,
        document_type="informational_page" if is_static_reference_page else "source_page_snapshot",
        title=f"{source.name} — page snapshot",
        original_url=source.url,
        mime_type=response.headers.get("content-type", "text/html").split(";")[0],
        meeting_date=None,
        body_name=source.body,
    )
    fetch.changed = snapshot_is_new

    discover_fn = CONNECTORS.get(source.connector, generic.discover)
    connector_crashed = False
    try:
        discovered = discover_fn(body, source.url, source_body=source.body)
    except Exception as exc:
        logger.exception("connector %s failed to parse source %s", source.connector, source.name)
        discovered = []
        connector_crashed = True
        connector_error = str(exc)[:2000]

    new_documents = 0
    for item in discovered:
        try:
            created = _fetch_and_store_document(db, source, fetch, item)
        except httpx.HTTPError as exc:
            logger.warning("failed to download %s: %s", item.url, exc)
            continue
        if created:
            new_documents += 1

    fetch.items_found = len(discovered)
    if connector_crashed:
        fetch.validation_status = "error"
        fetch.validation_message = f"connector {source.connector} raised: {connector_error}"
    elif len(discovered) == 0 and not is_static_reference_page:
        fetch.validation_status = "empty"
        fetch.validation_message = "connector ran but discovered 0 links -- source page may have changed structure"
    else:
        # A static_reference_page source discovering 0 linked documents is
        # expected (its payload is the page snapshot itself, not a link),
        # not a sign the page's structure broke.
        fetch.validation_status = "ok"

    fetch.duration_ms = int((time.monotonic() - started) * 1000)
    if new_documents:
        fetch.changed = True
        source.last_changed_at = now_utc()
    source.last_fetched_at = now_utc()
    source.consecutive_failures = 0
    source.last_error = None
    db.commit()
    logger.info(
        "fetched %s: %d links discovered, %d new document(s)",
        source.name,
        len(discovered),
        new_documents,
    )
    return fetch


def _fetch_and_store_document(db: Session, source: Source, fetch: Fetch, item: DiscoveredDocument) -> bool:
    response = fetch_url(item.url)
    content = response.content
    content_hash = sha256_hex(content)

    existing = (
        db.query(Document)
        .filter(Document.source_id == source.id, Document.content_hash == content_hash)
        .one_or_none()
    )
    if existing:
        return False

    content_type = response.headers.get("content-type", "").split(";")[0].strip()
    ext = EXT_BY_CONTENT_TYPE.get(content_type, "")
    if not ext:
        tail = item.url.split("?")[0].rsplit(".", 1)
        ext = f".{tail[1]}" if len(tail) == 2 and len(tail[1]) <= 5 else ".bin"

    directory = archive_dir_for(source.jurisdiction, item.body or source.body, item.meeting_date or now_utc())
    filename = f"{item.document_type}_{item.meeting_date or 'nodate'}_{content_hash[:10]}{ext}"
    archive_path = write_archive_file(directory, filename, content)
    write_metadata(
        directory,
        f"{filename}.metadata.json",
        {
            "original_url": item.url,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "content_hash": content_hash,
            "source_id": str(source.id),
            "content_type": content_type,
            "file_size_bytes": len(content),
            "http_status": response.status_code,
            "meeting_date": str(item.meeting_date) if item.meeting_date else None,
        },
    )

    document, _ = _upsert_document(
        db,
        source=source,
        fetch=fetch,
        archive_path=archive_path,
        content=content,
        content_hash=content_hash,
        document_type=item.document_type,
        title=item.title,
        original_url=item.url,
        mime_type=content_type or None,
        meeting_date=item.meeting_date,
        body_name=item.body or source.body,
    )

    if item.meeting_date and item.body:
        meeting = _upsert_meeting(db, source, item)
        _link_meeting_document(meeting, document, item.document_type)
        db.commit()

    return True


def _upsert_document(
    db: Session,
    *,
    source: Source,
    fetch: Fetch,
    archive_path,
    content: bytes,
    content_hash: str,
    document_type: str,
    title: str | None,
    original_url: str | None,
    mime_type: str | None,
    meeting_date: date | None,
    body_name: str | None,
) -> tuple[Document, bool]:
    existing = (
        db.query(Document)
        .filter(Document.source_id == source.id, Document.content_hash == content_hash)
        .one_or_none()
    )
    if existing:
        return existing, False

    doc = Document(
        source_id=source.id,
        fetch_id=fetch.id,
        title=title,
        document_type=document_type,
        original_url=original_url,
        archive_path=str(archive_path),
        content_hash=content_hash,
        mime_type=mime_type,
        file_size_bytes=len(content),
        meeting_date=meeting_date,
        jurisdiction=source.jurisdiction,
        agency=source.agency,
        body=body_name,
        # Snapshots are never AI-processed (excluded from CLASSIFIABLE_TYPES),
        # so parsing/chunking them is pure waste -- skip the parse queue
        # entirely rather than spend time extracting text nothing reads.
        parser_status="skipped" if document_type == "source_page_snapshot" else "pending",
    )
    db.add(doc)
    db.flush()
    return doc, True


def _upsert_meeting(db: Session, source: Source, item: DiscoveredDocument) -> Meeting:
    start_time = datetime(item.meeting_date.year, item.meeting_date.month, item.meeting_date.day, tzinfo=timezone.utc)
    meeting = (
        db.query(Meeting)
        .filter(
            Meeting.jurisdiction == source.jurisdiction,
            Meeting.body == item.body,
            Meeting.start_time == start_time,
        )
        .one_or_none()
    )
    if meeting is None:
        meeting = Meeting(
            jurisdiction=source.jurisdiction,
            agency=source.agency or source.jurisdiction,
            body=item.body,
            meeting_type=item.meeting_type,
            start_time=start_time,
            status="scheduled" if start_time > datetime.now(timezone.utc) else "completed",
        )
        db.add(meeting)
        db.flush()
    return meeting


MEETING_DOCUMENT_FIELD_BY_TYPE = {
    "agenda": "agenda_document_id",
    "packet": "packet_document_id",
    "minutes": "minutes_document_id",
}


def _link_meeting_document(meeting: Meeting, document: Document, document_type: str) -> None:
    field = MEETING_DOCUMENT_FIELD_BY_TYPE.get(document_type)
    if field and getattr(meeting, field) is None:
        setattr(meeting, field, document.id)
