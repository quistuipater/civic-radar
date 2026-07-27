"""Ingest Santa Cruz County Planning Commission agendas/minutes from the
county's legacy classic-ASP search tool (Microsoft Indexing Service era --
`www2.santacruzcountyca.gov/planning/plnmeetings/`). Not PrimeGov -- the
Board of Supervisors and Planning Commission are on separate platforms here
(unlike Ventura, where both shared one PrimeGov tenant); this platform has
no browsable "list recent meetings" page, only a full-text search form that
requires a non-empty keyword. Uses "agenda" as that keyword, since every
real agenda/minutes document contains it by definition -- a limitation of
the underlying full-text-index technology, not something a document-type
filter can route around. Verified live 2026-07-10.

Session-stateful: the search flow is GET (establish an ASP session) -> POST
QueryPLNIndex.asp -> POST DisplaySearchResult.ASP, all sharing one session
cookie or the second POST returns "Session has expired." The actual
document view pages (DisplayAgenda.aspx/DisplayMinutes.aspx) don't need
that session -- they're fetched as a second, independent step. Because of
the session-carrying search flow, this doesn't go through the generic
ingest_source()/CONNECTORS dispatch (same reasoning as onbase_agenda.py);
reuses pipeline.py's Meeting-document-linking helper directly.

Deliberately narrow scope: only pulls the primary agenda/minutes HTML view
pages found in search results, not the individual supporting-material PDF
exhibits (PdfFinder.asp links) referenced inside them -- same "packet, not
every embedded attachment" scoping PrimeGov/CivicPlus sources use elsewhere
in this project.
"""

import logging
import re
import time as time_module
from datetime import date, datetime, timezone
from urllib.parse import urljoin

import httpx
from dateutil import parser as dateutil_parser
from sqlalchemy.orm import Session

from app.archive import archive_dir_for, now_utc, sha256_hex, write_archive_file
from app.ingestion.pipeline import _link_meeting_document
from app.models import Document, Fetch, Meeting, Source

logger = logging.getLogger(__name__)

SEARCH_BASE = "https://www2.santacruzcountyca.gov/planning/plnmeetings/Search"

# Real MeetingType enum values from the search form's own <select> (verified
# live 2026-07-10) -- only Planning Commission is seeded today; the others
# exist on this same platform if ever needed.
PLANNING_COMMISSION_MEETING_TYPE = "1"

RESULT_LINK_RE = re.compile(
    r"<A target='_blank' title='' href='([^']+)' >(Agenda|Minute) - (\d{1,2}/\d{1,2}/\d{4})</A>"
)
DOCUMENT_TYPE_BY_LABEL = {"Agenda": "agenda", "Minute": "minutes"}


def _search(client: httpx.Client, meeting_type: str, search_term: str = "agenda") -> bytes:
    """Runs the 3-request session-stateful search flow and returns the
    results page body. Raises httpx.HTTPError on any request failure."""
    home_response = client.get(f"{SEARCH_BASE}/PLNsrchHome.asp", params={"Legacy": ""})
    home_response.raise_for_status()

    today = datetime.now(timezone.utc).date()
    query_response = client.post(
        f"{SEARCH_BASE}/QueryPLNIndex.asp",
        data={
            "Legacy": "",
            "txtSearchFor": search_term,
            "MeetingType": meeting_type,
            "SearchOptions": "/ClkBoard/BDSvData",
            "HighLight": "on",
            "SupportMaterial": "on",
            "FromAgendaDate": f"1/1/{today.year}",
            "ToAgendaDate": f"12/31/{today.year}",
            "NumOfRecords": "1000",
            "TimeOut": "60",
            "FromDate": "5/23/2001",
        },
    )
    query_response.raise_for_status()

    results_response = client.post(
        f"{SEARCH_BASE}/DisplaySearchResult.ASP",
        data={
            "Legacy": "",
            "HighLight": "on",
            "MeetingType": meeting_type,
            "txtSearchFor": search_term,
        },
    )
    results_response.raise_for_status()
    return results_response.content


def _parse_results(html_bytes: bytes, base_url: str) -> list[dict]:
    text = html_bytes.decode("windows-1252", errors="replace")
    results = []
    seen = set()
    for href, label, date_str in RESULT_LINK_RE.findall(text):
        document_type = DOCUMENT_TYPE_BY_LABEL.get(label)
        if document_type is None:
            continue
        try:
            meeting_date = dateutil_parser.parse(date_str).date()
        except (ValueError, OverflowError):
            continue
        url = urljoin(base_url, href)
        key = (document_type, meeting_date)
        if key in seen:
            continue
        seen.add(key)
        results.append({"document_type": document_type, "meeting_date": meeting_date, "url": url})
    return results


def _upsert_meeting(db: Session, source: Source, meeting_date: date) -> Meeting:
    start_time = datetime(meeting_date.year, meeting_date.month, meeting_date.day, tzinfo=timezone.utc)
    meeting = (
        db.query(Meeting)
        .filter(
            Meeting.jurisdiction == source.jurisdiction,
            Meeting.body == "Planning Commission",
            Meeting.start_time == start_time,
        )
        .one_or_none()
    )
    if meeting is None:
        meeting = Meeting(
            jurisdiction=source.jurisdiction,
            agency=source.agency or source.jurisdiction,
            body="Planning Commission",
            start_time=start_time,
            status="scheduled" if start_time > datetime.now(timezone.utc) else "completed",
        )
        db.add(meeting)
        db.flush()
    return meeting


def ingest_scc_planning_search(db: Session, source: Source) -> int:
    """Returns the number of new documents created."""
    started = time_module.monotonic()
    fetch = Fetch(source_id=source.id, status="pending")
    db.add(fetch)

    with httpx.Client(follow_redirects=True, timeout=60.0) as client:
        try:
            results_body = _search(client, PLANNING_COMMISSION_MEETING_TYPE)
        except httpx.HTTPError as exc:
            fetch.status = "error"
            fetch.error_message = str(exc)[:2000]
            fetch.validation_status = "error"
            fetch.validation_message = "search flow failed"
            fetch.duration_ms = int((time_module.monotonic() - started) * 1000)
            source.last_error = fetch.error_message
            source.consecutive_failures += 1
            source.last_fetched_at = now_utc()
            db.commit()
            logger.warning("Planning Commission search failed for source %s: %s", source.name, exc)
            return 0

        fetch.status = "ok"
        fetch.content_hash = sha256_hex(results_body)

        results = _parse_results(results_body, f"{SEARCH_BASE}/")
        created = 0
        for result in results:
            try:
                doc_response = client.get(result["url"])
                doc_response.raise_for_status()
            except httpx.HTTPError as exc:
                logger.warning("failed to fetch Planning Commission document %s: %s", result["url"], exc)
                continue

            content = doc_response.content
            content_hash = sha256_hex(content)
            existing = (
                db.query(Document)
                .filter(Document.source_id == source.id, Document.content_hash == content_hash)
                .one_or_none()
            )
            if existing is not None:
                continue

            directory = archive_dir_for(source.jurisdiction, "Planning Commission", result["meeting_date"])
            filename = f"{result['document_type']}_{result['meeting_date']}_{content_hash[:10]}.html"
            archive_path = write_archive_file(directory, filename, content)

            document = Document(
                source_id=source.id,
                fetch_id=fetch.id,
                title=f"{result['document_type'].capitalize()} — {result['meeting_date']}",
                document_type=result["document_type"],
                original_url=result["url"],
                archive_path=str(archive_path),
                content_hash=content_hash,
                mime_type="text/html",
                file_size_bytes=len(content),
                meeting_date=result["meeting_date"],
                jurisdiction=source.jurisdiction,
                agency=source.agency,
                body="Planning Commission",
                parser_status="pending",
            )
            db.add(document)
            db.flush()

            meeting = _upsert_meeting(db, source, result["meeting_date"])
            _link_meeting_document(meeting, document, result["document_type"])
            db.commit()
            created += 1

        fetch.items_found = len(results)
        if not results:
            fetch.validation_status = "empty"
            fetch.validation_message = "search returned 0 results -- session flow or search term may need revisiting"
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
            "fetched %s: %d result(s), %d new document(s)",
            source.name,
            len(results),
            created,
        )
        return created
