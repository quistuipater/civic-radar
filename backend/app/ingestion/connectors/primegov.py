"""Connector for PrimeGov public portals (e.g. ventura.primegov.com).

Ventura County's Board of Supervisors migrated its agendas off Legistar onto
PrimeGov at some point after the source was originally seeded — the old
ventura.legistar.com URL now returns a bare "Invalid parameters!" error page.
PrimeGov's public portal itself is a JS SPA, but it's backed by an open,
unauthenticated JSON API that the SPA calls to render meeting lists and to
download documents, so this connector talks to that API directly instead of
needing a headless browser (verified live 2026-07-05: no auth/session/cookie
required for either the meeting-list or document-download endpoints).

base_url is expected to look like
"https://<tenant>.primegov.com/public/portal?committee=<id>"; the tenant and
committee id are parsed out of it. Only the current year's archived meetings
plus any upcoming ones are fetched each cycle -- PrimeGov happily serves 25
years of history per committee, but re-downloading that whole backlog every
poll would be pointless load on the county's server for documents that never
change.
"""

import logging
from datetime import date, datetime
from urllib.parse import parse_qs, urlparse

from app.ingestion.connectors.base import DiscoveredDocument
from app.ingestion.http_client import fetch_url

logger = logging.getLogger(__name__)

# templateName (lowercased) -> our document_type; PrimeGov also lists an
# "HTML Agenda" rendition (compileOutputType 3) of the same content, which we
# skip in favor of the PDF rendition (compileOutputType 1).
DOCUMENT_TYPE_BY_TEMPLATE_NAME = {
    "agenda": "agenda",
    "packet": "packet",
    "minute orders": "minutes",
    "summary minutes": "minutes",
    "official summary minutes": "minutes",
}
PDF_COMPILE_OUTPUT_TYPE = 1


def discover(html_bytes: bytes, base_url: str) -> list[DiscoveredDocument]:
    parsed = urlparse(base_url)
    tenant_root = f"{parsed.scheme}://{parsed.netloc}"
    committee_id = parse_qs(parsed.query).get("committee", ["1"])[0]

    meetings: list[dict] = []
    try:
        upcoming = fetch_url(
            f"{tenant_root}/api/v2/PublicPortal/ListUpcomingMeetingsByCommitteeId?committeeId={committee_id}"
        ).json()
        meetings.extend(upcoming or [])
        archived = fetch_url(
            f"{tenant_root}/api/v2/PublicPortal/ListArchivedMeetingsByCommitteeId"
            f"?year={datetime.now().year}&committeeId={committee_id}"
        ).json()
        meetings.extend(archived or [])
    except Exception:
        logger.exception("primegov connector failed to list meetings for committee %s", committee_id)
        return []

    results: dict[str, DiscoveredDocument] = {}
    for meeting in meetings:
        meeting_date = _parse_meeting_date(meeting.get("dateTime"))
        for doc in meeting.get("documentList") or []:
            if doc.get("compileOutputType") != PDF_COMPILE_OUTPUT_TYPE:
                continue
            template_name = (doc.get("templateName") or "").strip()
            document_type = DOCUMENT_TYPE_BY_TEMPLATE_NAME.get(template_name.lower())
            if document_type is None or not doc.get("templateId"):
                continue
            doc_url = (
                f"{tenant_root}/Public/CompiledDocument"
                f"?meetingTemplateId={doc['templateId']}&compileOutputType={PDF_COMPILE_OUTPUT_TYPE}"
            )
            if doc_url in results:
                continue
            results[doc_url] = DiscoveredDocument(
                url=doc_url,
                document_type=document_type,
                title=f"{template_name} — {meeting.get('date') or meeting_date or ''}".strip(" —"),
                meeting_date=meeting_date,
                body="Board of Supervisors",
                meeting_type=template_name,
            )
    return list(results.values())


def _parse_meeting_date(date_time_str: str | None) -> date | None:
    if not date_time_str:
        return None
    try:
        return datetime.fromisoformat(date_time_str).date()
    except ValueError:
        return None
