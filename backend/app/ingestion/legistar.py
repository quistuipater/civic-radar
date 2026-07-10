"""Ingest City of Boston meeting agendas/minutes from Legistar's public web
API (webapi.legistar.com) -- Boston's council/committee platform, verified
live 2026-07-10. Structurally different from every other Document-based
source: it's a real, documented, unauthenticated REST/OData API
(`GET v1/{client}/Events`), not an HTML page to scrape or a session-stateful
POST/GET flow like OnBase -- agenda/minutes PDFs are plain, permanently
addressable URLs on `{client}.legistar1.com`, no cookie/session dance
required. Because of that shape mismatch with ingest_source()/CONNECTORS
(same reasoning as meeting_audio.py/crime_data.py/onbase_agenda.py), this
gets its own ingestion function; it reuses pipeline.py's Meeting-document-
linking helper directly since that part is identical to every other source.

Legistar hosts every one of a city's bodies in one shared system (City
Council, its committees, Zoning Board of Appeal, School Committee, etc.) --
`source.url` is expected to look like
`https://webapi.legistar.com/v1/{client}/Events?bodyId={N}`, a convention
specific to this module (not a real Legistar OData query -- `_events_url`
below parses `client`/`bodyId` back out and builds the real
`$filter=(EventBodyId eq N) and (EventDate ge ...)` query itself, rather
than trying to splice a lookback window into an arbitrary pre-existing
`$filter` the source URL might already carry) so seeding a new body is just
"look up its BodyId and change the query param," not a config decision that
this module enforces on its own (though see CLAUDE.md's Phase 1 boundary:
school boards are explicitly out of scope for this project, so don't seed a
Source for Boston School Committee without revisiting that).

A single BodyId can have 1000+ historical events -- too many to re-fetch in
full every poll -- so `_events_url` always scopes the query to a rolling
`LOOKBACK_DAYS`-day window rather than ever crawling full history.
Re-scanning the same recent window on every poll is safe and cheap:
documents are deduped by content hash, so already-ingested PDFs are just
skipped.
"""

import logging
import time as time_module
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import httpx
from sqlalchemy.orm import Session

from app.archive import archive_dir_for, now_utc, sha256_hex, write_archive_file, write_metadata
from app.ingestion.pipeline import _link_meeting_document
from app.models import Document, Fetch, Meeting, Source

logger = logging.getLogger(__name__)

LOOKBACK_DAYS = 120


def _events_url(source_url: str) -> str:
    """`https://webapi.legistar.com/v1/boston/Events?bodyId=138` ->
    a real Legistar Events query, scoped to that body and to the last
    LOOKBACK_DAYS days."""
    parsed = urlparse(source_url)
    client = [p for p in parsed.path.split("/") if p][1]
    body_id = parse_qs(parsed.query)["bodyId"][0]
    cutoff = (datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    odata_filter = f"(EventBodyId eq {body_id}) and (EventDate ge datetime'{cutoff}')"
    return f"https://webapi.legistar.com/v1/{client}/Events?$filter={odata_filter}"


def _parse_events(events: list[dict]) -> list[dict]:
    """One dict per event that has at least one real document link -- events
    for meetings that haven't happened yet and have no agenda posted are
    skipped, same as onbase_agenda.py does for meetings with no document
    links."""
    rows = []
    for event in events:
        documents = []
        if event.get("EventAgendaFile"):
            documents.append({"document_type": "agenda", "url": event["EventAgendaFile"]})
        if event.get("EventMinutesFile"):
            documents.append({"document_type": "minutes", "url": event["EventMinutesFile"]})
        if not documents:
            continue
        try:
            start_time = datetime.fromisoformat(event["EventDate"]).replace(tzinfo=timezone.utc)
        except (KeyError, ValueError):
            continue
        rows.append(
            {
                "event_id": event["EventId"],
                "body": event["EventBodyName"],
                "start_time": start_time,
                "documents": documents,
            }
        )
    return rows


def _upsert_meeting(db: Session, source: Source, event_row: dict) -> Meeting:
    meeting = (
        db.query(Meeting)
        .filter(
            Meeting.jurisdiction == source.jurisdiction,
            Meeting.body == event_row["body"],
            Meeting.start_time == event_row["start_time"],
        )
        .one_or_none()
    )
    if meeting is None:
        meeting = Meeting(
            jurisdiction=source.jurisdiction,
            agency=source.agency or source.jurisdiction,
            body=event_row["body"],
            start_time=event_row["start_time"],
            status="scheduled" if event_row["start_time"] > datetime.now(timezone.utc) else "completed",
        )
        db.add(meeting)
        db.flush()
    return meeting


def ingest_legistar(db: Session, source: Source) -> int:
    """Returns the number of new documents created."""
    started = time_module.monotonic()
    fetch = Fetch(source_id=source.id, status="pending")
    db.add(fetch)

    events_url = _events_url(source.url)

    with httpx.Client(follow_redirects=True, timeout=60.0) as client:
        try:
            response = client.get(events_url)
            response.raise_for_status()
            events = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            fetch.status = "error"
            fetch.error_message = str(exc)[:2000]
            fetch.validation_status = "error"
            fetch.validation_message = "Legistar Events fetch failed"
            fetch.duration_ms = int((time_module.monotonic() - started) * 1000)
            source.last_error = fetch.error_message
            source.consecutive_failures += 1
            source.last_fetched_at = now_utc()
            db.commit()
            logger.warning("Legistar Events fetch failed for source %s: %s", source.name, exc)
            return 0

        fetch.http_status = response.status_code
        fetch.status = "ok"

        raw_directory = archive_dir_for(source.jurisdiction, source.body, now_utc())
        write_metadata(
            raw_directory,
            f"legistar_events_poll_{now_utc().strftime('%Y%m%dT%H%M%S')}.json",
            {"source_id": str(source.id), "events_url": events_url, "count": len(events), "events": events},
        )

        event_rows = _parse_events(events)

        created = 0
        for event_row in event_rows:
            for doc in event_row["documents"]:
                try:
                    pdf_response = client.get(doc["url"])
                    pdf_response.raise_for_status()
                except httpx.HTTPError as exc:
                    logger.warning(
                        "failed to download Legistar document %s for event %s: %s",
                        doc["url"],
                        event_row["event_id"],
                        exc,
                    )
                    continue

                content = pdf_response.content
                content_hash = sha256_hex(content)
                existing = (
                    db.query(Document)
                    .filter(Document.source_id == source.id, Document.content_hash == content_hash)
                    .one_or_none()
                )
                if existing is not None:
                    continue

                doc_directory = archive_dir_for(source.jurisdiction, event_row["body"], event_row["start_time"])
                filename = f"{doc['document_type']}_{event_row['start_time'].date()}_{content_hash[:10]}.pdf"
                archive_path = write_archive_file(doc_directory, filename, content)
                write_metadata(
                    doc_directory,
                    f"{filename}.metadata.json",
                    {
                        "original_url": doc["url"],
                        "legistar_event_id": event_row["event_id"],
                        "content_hash": content_hash,
                        "source_id": str(source.id),
                        "file_size_bytes": len(content),
                    },
                )

                document = Document(
                    source_id=source.id,
                    fetch_id=fetch.id,
                    title=f"{doc['document_type'].capitalize()} — {event_row['start_time'].date()}",
                    document_type=doc["document_type"],
                    original_url=doc["url"],
                    archive_path=str(archive_path),
                    content_hash=content_hash,
                    mime_type="application/pdf",
                    file_size_bytes=len(content),
                    meeting_date=event_row["start_time"].date(),
                    jurisdiction=source.jurisdiction,
                    agency=source.agency,
                    body=event_row["body"],
                    parser_status="pending",
                )
                db.add(document)
                db.flush()

                meeting = _upsert_meeting(db, source, event_row)
                _link_meeting_document(meeting, document, doc["document_type"])
                db.commit()
                created += 1

        fetch.items_found = sum(len(e["documents"]) for e in event_rows)
        if not events:
            fetch.validation_status = "empty"
            fetch.validation_message = f"no events returned for the last {LOOKBACK_DAYS} days"
        else:
            fetch.validation_status = "ok"
        fetch.duration_ms = int((time_module.monotonic() - started) * 1000)
        if created:
            fetch.changed = True
            source.last_changed_at = now_utc()
        source.last_fetched_at = now_utc()
        source.consecutive_failures = 0
        source.last_error = None
        db.commit()
        logger.info(
            "fetched %s: %d event(s), %d new document(s)",
            source.name,
            len(event_rows),
            created,
        )
        return created
