"""Ingest City of Santa Cruz council/commission agendas from OnBase Agenda
Online (ecm.cityofsantacruz.com/OnBaseAgendaOnline/) -- a Hyland OnBase
deployment, not CivicPlus (Ventura's platform). Structurally different from
every other Document-based source: OnBase's document links don't resolve to
a PDF via a plain GET. The homepage link is a "please wait" loading page
whose own JS does a POST (InvokeDownloadMeetingDocument for the Agenda/
Minutes types, or InvokeDownloadAttachment for the Agenda Packet type,
verified live 2026-07-10 via each type's real href) followed by a GET
(ViewDocument) to actually stream the PDF bytes -- both requests need the
same session cookie the homepage GET establishes. Because of that,
ingestion here doesn't go through the generic ingest_source()/CONNECTORS
dispatch pipeline.py uses for everything else (same reasoning as
meeting_audio.py/crime_data.py needing their own bespoke ingestion
functions); it reuses pipeline.py's Meeting-document-linking helper
directly, since that part of the logic is identical to every other source.

The homepage lists every board/committee's upcoming and recent meetings on
a single page, each row carrying data-meeting-id, data-sortable-type (body
name), and data-sortable-data (a real Unix timestamp) -- more reliable
ground truth for meeting identity/date than the regex-based date-guessing
other connectors need, so meetings here are looked up/created directly by
that id/timestamp rather than via a fuzzy date match.
"""

import logging
from datetime import datetime, timezone
from urllib.parse import parse_qs, quote, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

from app.archive import archive_dir_for, now_utc, sha256_hex, write_archive_file, write_metadata
from app.ingestion.pipeline import _link_meeting_document
from app.models import Document, Fetch, Meeting, Source

logger = logging.getLogger(__name__)

# OnBase's own numeric documentType enum, as seen in real hrefs on the
# homepage (verified live 2026-07-10) -- only the types we've actually
# observed real links for are mapped; anything else is skipped rather than
# guessed at.
DOCUMENT_TYPE_BY_ONBASE_TYPE = {
    "1": "agenda",
    "2": "minutes",
    "5": "packet",
}


def _parse_meetings(html_bytes: bytes, base_url: str) -> list[dict]:
    """One dict per real meeting row on the homepage, deduped by meeting id
    (each row is rendered twice in the markup, once per responsive
    breakpoint)."""
    soup = BeautifulSoup(html_bytes, "html.parser")
    meetings: dict[str, dict] = {}
    for row in soup.select("tr.meeting-row[data-meeting-id]"):
        meeting_id = row["data-meeting-id"]
        if meeting_id in meetings:
            continue
        body_cell = row.select_one("td[data-sortable-type='mtgType']")
        time_cell = row.select_one("td[data-sortable-type='mtgTime']")
        if body_cell is None or time_cell is None or not time_cell.get("data-sortable-data"):
            continue
        body = body_cell.get_text(strip=True)
        start_time = datetime.fromtimestamp(int(time_cell["data-sortable-data"]), tz=timezone.utc)

        documents = []
        seen_hrefs = set()
        for link in row.select("a[href*='ownloadfile']"):  # matches Downloadfile/DownloadFile (case varies)
            href = link.get("href")
            if not href or href in seen_hrefs:
                continue
            seen_hrefs.add(href)
            params = parse_qs(urlparse(href).query)
            onbase_type = (params.get("documentType") or [None])[0]
            document_type = DOCUMENT_TYPE_BY_ONBASE_TYPE.get(onbase_type)
            if document_type is None:
                continue
            filename = urlparse(href).path.rsplit("/", 1)[-1]
            documents.append(
                {
                    "document_type": document_type,
                    "onbase_type": onbase_type,
                    "filename": filename,
                    "is_attachment": "isAttachment=True" in href,
                }
            )
        if documents:
            meetings[meeting_id] = {
                "meeting_id": meeting_id,
                "body": body,
                "start_time": start_time,
                "documents": documents,
            }
    return list(meetings.values())


def _resolve_pdf(client: httpx.Client, base_url: str, meeting_id: str, doc: dict) -> httpx.Response:
    """Replays OnBase's own client-side 2-step download flow (POST then GET)
    on the shared session client so both requests carry the same cookie.
    itemId/publishId/isSection default to 0/0/false for both invoke
    endpoints -- confirmed live 2026-07-10 that the server accepts those
    defaults regardless of what (if anything) the invoke response echoes
    back for them.
    """
    encoded_name = quote(doc["filename"])
    if doc["is_attachment"]:
        invoke_url = (
            f"{base_url}/OnBaseAgendaOnline/Documents/InvokeDownloadAttachment/{encoded_name}"
            f"?meetingId={meeting_id}&itemId=0&publishId=0&isSection=false&documentType={doc['onbase_type']}"
        )
    else:
        invoke_url = (
            f"{base_url}/OnBaseAgendaOnline/Documents/InvokeDownloadMeetingDocument/{encoded_name}"
            f"?meetingId={meeting_id}&documentType={doc['onbase_type']}"
        )
    invoke_response = client.post(invoke_url, content=b"")
    invoke_response.raise_for_status()
    data = invoke_response.json()

    view_url = (
        f"{base_url}/OnBaseAgendaOnline/Documents/ViewDocument/{quote(data['DocumentName'])}"
        f"?meetingId={data.get('MeetingId', meeting_id)}&documentType={doc['onbase_type']}"
        f"&itemId={data.get('ItemId', 0)}&publishId={data.get('PublishId', 0)}"
        f"&isSection={str(data.get('IsSection', False)).lower()}"
    )
    view_response = client.get(view_url)
    view_response.raise_for_status()
    return view_response


def _upsert_meeting(db: Session, source: Source, meeting_row: dict) -> Meeting:
    meeting = (
        db.query(Meeting)
        .filter(
            Meeting.jurisdiction == source.jurisdiction,
            Meeting.body == meeting_row["body"],
            Meeting.start_time == meeting_row["start_time"],
        )
        .one_or_none()
    )
    if meeting is None:
        meeting = Meeting(
            jurisdiction=source.jurisdiction,
            agency=source.agency or source.jurisdiction,
            body=meeting_row["body"],
            start_time=meeting_row["start_time"],
            status="scheduled" if meeting_row["start_time"] > datetime.now(timezone.utc) else "completed",
        )
        db.add(meeting)
        db.flush()
    return meeting


def ingest_onbase_agenda(db: Session, source: Source) -> int:
    """Returns the number of new documents created."""
    import time as time_module

    started = time_module.monotonic()
    fetch = Fetch(source_id=source.id, status="pending")
    db.add(fetch)

    base_url = f"{urlparse(source.url).scheme}://{urlparse(source.url).netloc}"

    with httpx.Client(follow_redirects=True, timeout=60.0) as client:
        try:
            homepage = client.get(source.url)
            homepage.raise_for_status()
        except httpx.HTTPError as exc:
            fetch.status = "error"
            fetch.error_message = str(exc)[:2000]
            fetch.validation_status = "error"
            fetch.validation_message = "HTTP fetch failed"
            fetch.duration_ms = int((time_module.monotonic() - started) * 1000)
            source.last_error = fetch.error_message
            source.consecutive_failures += 1
            source.last_fetched_at = now_utc()
            db.commit()
            logger.warning("OnBase homepage fetch failed for source %s: %s", source.name, exc)
            return 0

        body = homepage.content
        page_hash = sha256_hex(body)
        directory = archive_dir_for(source.jurisdiction, source.body, now_utc())
        fetch.http_status = homepage.status_code
        fetch.content_hash = page_hash
        fetch.status = "ok"

        snapshot_path = write_archive_file(directory, f"source_snapshot_{page_hash[:12]}.html", body)
        fetch.archive_path = str(snapshot_path)
        existing_snapshot = (
            db.query(Document)
            .filter(Document.source_id == source.id, Document.content_hash == page_hash)
            .one_or_none()
        )
        if existing_snapshot is None:
            db.add(
                Document(
                    source_id=source.id,
                    fetch_id=fetch.id,
                    title=f"{source.name} — page snapshot",
                    document_type="source_page_snapshot",
                    original_url=source.url,
                    archive_path=str(snapshot_path),
                    content_hash=page_hash,
                    mime_type=homepage.headers.get("content-type", "text/html").split(";")[0],
                    file_size_bytes=len(body),
                    jurisdiction=source.jurisdiction,
                    agency=source.agency,
                    body=source.body,
                    parser_status="skipped",
                )
            )

        try:
            meeting_rows = _parse_meetings(body, base_url)
        except Exception:
            logger.exception("failed to parse OnBase homepage for source %s", source.name)
            meeting_rows = []

        created = 0
        for meeting_row in meeting_rows:
            for doc in meeting_row["documents"]:
                try:
                    pdf_response = _resolve_pdf(client, base_url, meeting_row["meeting_id"], doc)
                except httpx.HTTPError as exc:
                    logger.warning(
                        "failed to resolve OnBase document %s for meeting %s: %s",
                        doc["filename"],
                        meeting_row["meeting_id"],
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

                doc_directory = archive_dir_for(source.jurisdiction, meeting_row["body"], meeting_row["start_time"])
                filename = f"{doc['document_type']}_{meeting_row['start_time'].date()}_{content_hash[:10]}.pdf"
                archive_path = write_archive_file(doc_directory, filename, content)
                write_metadata(
                    doc_directory,
                    f"{filename}.metadata.json",
                    {
                        "original_filename": doc["filename"],
                        "onbase_meeting_id": meeting_row["meeting_id"],
                        "content_hash": content_hash,
                        "source_id": str(source.id),
                        "file_size_bytes": len(content),
                    },
                )

                document = Document(
                    source_id=source.id,
                    fetch_id=fetch.id,
                    title=f"{doc['document_type'].capitalize()} — {meeting_row['start_time'].date()}",
                    document_type=doc["document_type"],
                    original_url=source.url,
                    archive_path=str(archive_path),
                    content_hash=content_hash,
                    mime_type="application/pdf",
                    file_size_bytes=len(content),
                    meeting_date=meeting_row["start_time"].date(),
                    jurisdiction=source.jurisdiction,
                    agency=source.agency,
                    body=meeting_row["body"],
                    parser_status="pending",
                )
                db.add(document)
                db.flush()

                meeting = _upsert_meeting(db, source, meeting_row)
                _link_meeting_document(meeting, document, doc["document_type"])
                db.commit()
                created += 1

        fetch.items_found = sum(len(m["documents"]) for m in meeting_rows)
        if not meeting_rows:
            fetch.validation_status = "empty"
            fetch.validation_message = "no meeting rows with document links found -- page structure may have changed"
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
            "fetched %s: %d meeting(s), %d new document(s)",
            source.name,
            len(meeting_rows),
            created,
        )
        return created
