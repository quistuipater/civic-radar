"""Deterministic counts/tables for a narrative summary period -- documents
filed, meetings held/upcoming, alerts by level, filing volume by agency.
Kept separate from the AI-written overview (generate.py) so every number
on the report is a real query result, never something the model computed
or transcribed -- the model only narrates numbers this module already
handed it (see generate.py's prompt, which passes these as facts).
"""

from datetime import datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.models import AiOutput, Alert, Document, Meeting, NarrativeSummary

UPCOMING_WINDOW_DAYS = 14


def _document_url(document: Document) -> str:
    # original_url (the real source, e.g. the agency's own site/NetFile) is
    # always preferred when present; the /documents/{id} fallback is only
    # for documents ingested by a route that never captured a source URL,
    # and must be absolute -- an emailed summary has no browser origin to
    # resolve a relative link against.
    return document.original_url or f"{settings.dashboard_base_url}/documents/{document.id}"


def compute_stats(db: Session, period_start: datetime, period_end: datetime) -> dict:
    documents_filed = (
        db.query(Document).filter(Document.created_at.between(period_start, period_end)).count()
    )

    meetings_held = (
        db.query(Meeting)
        .filter(Meeting.start_time.between(period_start, period_end))
        .order_by(Meeting.start_time)
        .all()
    )

    upcoming_until = period_end + timedelta(days=UPCOMING_WINDOW_DAYS)
    meetings_upcoming = (
        db.query(Meeting)
        .filter(Meeting.start_time.between(period_end, upcoming_until))
        .order_by(Meeting.start_time)
        .all()
    )

    meeting_doc_ids = {
        doc_id
        for m in (meetings_held + meetings_upcoming)
        for doc_id in (m.agenda_document_id, m.packet_document_id, m.minutes_document_id)
        if doc_id
    }
    documents_by_id = (
        {d.id: d for d in db.query(Document).filter(Document.id.in_(meeting_doc_ids))} if meeting_doc_ids else {}
    )

    alerts_by_level = dict(
        db.query(Alert.alert_level, func.count())
        .filter(Alert.created_at.between(period_start, period_end))
        .group_by(Alert.alert_level)
        .all()
    )
    alerts_raised = sum(alerts_by_level.values())

    review_queue_count = (
        db.query(AiOutput)
        .join(Document, Document.id == AiOutput.input_ref_id)
        .filter(
            AiOutput.created_at.between(period_start, period_end),
            AiOutput.task_type == "classification",
            AiOutput.output_json["human_review_required"].astext == "true",
            AiOutput.reviewed.is_(False),
        )
        .count()
    )

    filing_by_agency = (
        db.query(Document.agency, func.count())
        .filter(Document.created_at.between(period_start, period_end), Document.agency.isnot(None))
        .group_by(Document.agency)
        .order_by(func.count().desc())
        .limit(10)
        .all()
    )

    new_notices = (
        db.query(Document)
        .filter(Document.created_at.between(period_start, period_end), Document.document_type == "notice")
        .order_by(Document.created_at.desc())
        .limit(20)
        .all()
    )

    return {
        "documents_filed": documents_filed,
        "meetings_held": [_meeting_row(m, documents_by_id) for m in meetings_held],
        "meetings_upcoming": [_meeting_row(m, documents_by_id) for m in meetings_upcoming],
        "alerts_raised": alerts_raised,
        "alerts_by_level": {str(level): count for level, count in sorted(alerts_by_level.items(), reverse=True)},
        "review_queue_count": review_queue_count,
        "filing_by_agency": [{"agency": agency, "count": count} for agency, count in filing_by_agency],
        "new_notices": [
            {"title": d.title or "(untitled)", "meta": d.agency, "url": _document_url(d)} for d in new_notices
        ],
    }


def _meeting_row(meeting: Meeting, documents_by_id: dict) -> dict:
    # Prefer whichever of these actually exists, in the order a reader
    # would want it: the agenda (what will be discussed), else the full
    # packet, else the minutes (what already happened) -- a meeting can
    # have any subset of these linked depending on where it is in its
    # lifecycle.
    doc_id = meeting.agenda_document_id or meeting.packet_document_id or meeting.minutes_document_id
    document = documents_by_id.get(doc_id) if doc_id else None
    return {
        "date": meeting.start_time.date().isoformat() if meeting.start_time else None,
        "body": meeting.body,
        "meeting_type": meeting.meeting_type,
        "url": _document_url(document) if document else None,
    }


def next_issue_number(db: Session, period_type: str) -> int:
    return db.query(NarrativeSummary).filter(NarrativeSummary.period_type == period_type).count() + 1
