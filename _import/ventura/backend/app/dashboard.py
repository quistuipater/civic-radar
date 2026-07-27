"""Server-rendered dashboard (prd.md 16). Deliberately dense/table-first per the
UX principles in 16.1 — no client-side framework, since this needs to run fully
local without a build step.
"""

import re
import uuid
from datetime import datetime, timedelta, timezone

from dateutil import parser as dateutil_parser
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.ai.classify import classify_document
from app.db import get_db
from app.export.digest import DEFAULT_WINDOW_HOURS, build_daily_digest
from app.issue_matching import suggest_issues_for_document
from app.models import (
    AgendaItem,
    AiOutput,
    Alert,
    Document,
    Fetch,
    Issue,
    IssueLink,
    ManualSubmission,
    Meeting,
    MeetingTranscript,
    Source,
)
from app.routers.review import review_queue

router = APIRouter(tags=["dashboard"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/")
def home(request: Request, db: Session = Depends(get_db)):
    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=24)
    week_ahead = now + timedelta(days=7)

    stats = {
        "new_documents_24h": db.query(Document).filter(Document.created_at >= since).count(),
        "review_queue_size": db.query(Alert).filter(Alert.reviewed.is_(False), Alert.alert_level >= 3).count(),
        "source_failures": db.query(Source).filter(Source.consecutive_failures >= 3).count(),
        "upcoming_meetings": db.query(Meeting).filter(Meeting.start_time.between(now, week_ahead)).count(),
    }
    alerts = (
        db.query(Alert)
        .filter(Alert.alert_level >= 3, Alert.reviewed.is_(False))
        .order_by(Alert.alert_level.desc(), Alert.created_at.desc())
        .limit(20)
        .all()
    )
    meetings = (
        db.query(Meeting)
        .filter(Meeting.start_time.between(now, week_ahead))
        .order_by(Meeting.start_time.asc())
        .limit(20)
        .all()
    )
    documents = (
        db.query(Document)
        .filter(Document.document_type != "source_page_snapshot")
        .order_by(Document.created_at.desc())
        .limit(20)
        .all()
    )
    failing_sources = db.query(Source).filter(Source.consecutive_failures >= 3).all()

    return templates.TemplateResponse(
        "home.html",
        {
            "request": request,
            "stats": stats,
            "alerts": alerts,
            "meetings": meetings,
            "documents": documents,
            "failing_sources": failing_sources,
        },
    )


@router.get("/digest")
def digest_page(request: Request, window_hours: int = DEFAULT_WINDOW_HOURS, db: Session = Depends(get_db)):
    digest = build_daily_digest(db, window_hours=window_hours)
    return templates.TemplateResponse("digest.html", {"request": request, "digest": digest})


@router.get("/sources")
def sources_page(request: Request, db: Session = Depends(get_db)):
    sources = db.query(Source).order_by(Source.name).all()
    latest_fetches = {}
    for s in sources:
        latest_fetches[s.id] = (
            db.query(Fetch).filter(Fetch.source_id == s.id).order_by(Fetch.fetched_at.desc()).first()
        )
    return templates.TemplateResponse(
        "sources.html", {"request": request, "sources": sources, "latest_fetches": latest_fetches}
    )


@router.get("/review-queue")
def review_queue_page(request: Request, db: Session = Depends(get_db)):
    data = review_queue(db)
    return templates.TemplateResponse("review_queue.html", {"request": request, "data": data})


@router.post("/review/{item_id}/approve")
def dashboard_approve(item_id: uuid.UUID, db: Session = Depends(get_db)):
    alert = db.get(Alert, item_id)
    if alert:
        alert.reviewed = True
        alert.status = "approved"
        db.commit()
    return RedirectResponse(url="/review-queue", status_code=303)


@router.post("/review/{item_id}/reject")
def dashboard_reject(item_id: uuid.UUID, db: Session = Depends(get_db)):
    alert = db.get(Alert, item_id)
    if alert:
        alert.reviewed = True
        alert.status = "rejected"
        db.commit()
    return RedirectResponse(url="/review-queue", status_code=303)


@router.get("/issues")
def issue_list_page(request: Request, db: Session = Depends(get_db)):
    issues = db.query(Issue).order_by(Issue.updated_at.desc()).all()
    return templates.TemplateResponse("issue_list.html", {"request": request, "issues": issues})


@router.post("/issues/new")
def create_issue_form(
    title: str = Form(...),
    slug: str = Form(...),
    jurisdiction: str = Form(""),
    summary: str = Form(""),
    db: Session = Depends(get_db),
):
    if not db.query(Issue).filter(Issue.slug == slug).one_or_none():
        db.add(Issue(title=title, slug=slug, jurisdiction=jurisdiction or None, summary=summary or None))
        db.commit()
    return RedirectResponse(url="/issues", status_code=303)


@router.get("/issues/{issue_id}")
def issue_detail_page(issue_id: uuid.UUID, request: Request, db: Session = Depends(get_db)):
    issue = db.get(Issue, issue_id)
    if not issue:
        raise HTTPException(status_code=404, detail="issue not found")
    events = sorted(issue.events, key=lambda e: e.event_date or e.detected_at, reverse=True)
    link_rows = db.query(IssueLink).filter(IssueLink.issue_id == issue_id, IssueLink.document_id.isnot(None)).all()
    links = [(link, db.get(Document, link.document_id)) for link in link_rows]
    links = [(link, doc) for link, doc in links if doc is not None]
    return templates.TemplateResponse(
        "issue_detail.html", {"request": request, "issue": issue, "events": events, "links": links}
    )


@router.get("/issues/{issue_id}/brief.md")
def issue_brief_redirect(issue_id: uuid.UUID):
    return RedirectResponse(url=f"/api/issues/{issue_id}/brief.md")


def _meeting_source_context(db: Session, meeting: Meeting | None) -> dict:
    """The specific agenda/packet/minutes documents a Meeting points to (as
    opposed to the broader date+body document match, which can't tell which
    row *is* the agenda vs. the minutes), plus the meeting-results summary
    for the minutes doc if one's been extracted. Deliberately meeting-level,
    not per-agenda-item -- see app/ai/meeting_results.py for why matching a
    specific decision back to a specific agenda item isn't attempted.
    """
    if meeting is None:
        return {"key_documents": {}, "meeting_results": None, "transcripts": []}
    key_documents = {
        "agenda": db.get(Document, meeting.agenda_document_id) if meeting.agenda_document_id else None,
        "packet": db.get(Document, meeting.packet_document_id) if meeting.packet_document_id else None,
        "minutes": db.get(Document, meeting.minutes_document_id) if meeting.minutes_document_id else None,
    }
    meeting_results = None
    if meeting.minutes_document_id:
        meeting_results = (
            db.query(AiOutput)
            .filter(
                AiOutput.input_ref_type == "document",
                AiOutput.input_ref_id == meeting.minutes_document_id,
                AiOutput.task_type == "meeting_results_summary",
            )
            .order_by(AiOutput.created_at.desc())
            .first()
        )
    transcripts = (
        db.query(MeetingTranscript)
        .filter(MeetingTranscript.meeting_id == meeting.id)
        .order_by(MeetingTranscript.processed_at.asc())
        .all()
    )
    return {"key_documents": key_documents, "meeting_results": meeting_results, "transcripts": transcripts}


# "Approval of the Minutes" items describe the *prior* meeting(s) they're
# approving in free text ("draft minutes from the April 9 and June 11, 2026
# meetings") -- a completely different document than the current meeting's
# own (usually not-yet-existing) minutes, which _meeting_source_context
# can't resolve. Matches "Month Day" with an optional ", Year" so a list
# like "April 9 and June 11, 2026" -- where only the last date states the
# year -- still resolves both: any date missing a year borrows the one
# year actually stated in the text.
REFERENCED_DATE_RE = re.compile(r"([A-Z][a-z]+\.?\s+\d{1,2})(?:,?\s+(\d{4}))?")


def _referenced_minutes_documents(db: Session, item: AgendaItem, meeting: Meeting | None) -> list[tuple]:
    """For items about approving prior minutes specifically -- narrowly
    scoped to that (rather than running on every item's description) since
    the date regex isn't precise enough to risk false positives elsewhere.
    Returns [(date, Document|None)], the document present only if that
    date's minutes have actually been archived for this same body.
    """
    if meeting is None or "minutes" not in (item.title or "").lower():
        return []
    text = item.description or item.title or ""
    matches = REFERENCED_DATE_RE.findall(text)
    if not matches:
        return []
    shared_year = next((int(y) for _, y in matches if y), None)

    results = []
    seen_dates = set()
    for month_day, year_str in matches:
        year = int(year_str) if year_str else shared_year
        if year is None:
            continue
        try:
            parsed_date = dateutil_parser.parse(f"{month_day} {year}").date()
        except (ValueError, OverflowError):
            continue
        if parsed_date in seen_dates:
            continue
        seen_dates.add(parsed_date)
        document = (
            db.query(Document)
            .filter(
                Document.document_type == "minutes",
                Document.body == meeting.body,
                Document.meeting_date == parsed_date,
            )
            .one_or_none()
        )
        results.append((parsed_date, document))
    return sorted(results, key=lambda pair: pair[0])


@router.get("/meetings/{meeting_id}")
def meeting_detail_page(meeting_id: uuid.UUID, request: Request, db: Session = Depends(get_db)):
    meeting = db.get(Meeting, meeting_id)
    if not meeting:
        raise HTTPException(status_code=404, detail="meeting not found")
    documents = (
        db.query(Document)
        .filter(Document.meeting_date == (meeting.start_time.date() if meeting.start_time else None))
        .filter(Document.body == meeting.body)
        .all()
    )
    agenda_items = db.query(AgendaItem).filter(AgendaItem.meeting_id == meeting_id).all()
    return templates.TemplateResponse(
        "meeting_detail.html",
        {
            "request": request,
            "meeting": meeting,
            "documents": documents,
            "agenda_items": agenda_items,
            **_meeting_source_context(db, meeting),
        },
    )


@router.get("/agenda-items/{agenda_item_id}")
def agenda_item_detail_page(agenda_item_id: uuid.UUID, request: Request, db: Session = Depends(get_db)):
    item = db.get(AgendaItem, agenda_item_id)
    if not item:
        raise HTTPException(status_code=404, detail="agenda item not found")
    meeting = db.get(Meeting, item.meeting_id)
    return templates.TemplateResponse(
        "agenda_item_detail.html",
        {
            "request": request,
            "item": item,
            "meeting": meeting,
            "referenced_minutes": _referenced_minutes_documents(db, item, meeting),
            **_meeting_source_context(db, meeting),
        },
    )


@router.get("/transcripts/{transcript_id}")
def transcript_detail_page(transcript_id: uuid.UUID, request: Request, db: Session = Depends(get_db)):
    transcript = db.get(MeetingTranscript, transcript_id)
    if not transcript:
        raise HTTPException(status_code=404, detail="transcript not found")
    meeting = db.get(Meeting, transcript.meeting_id) if transcript.meeting_id else None
    return templates.TemplateResponse(
        "transcript_detail.html",
        {"request": request, "transcript": transcript, "meeting": meeting},
    )


@router.get("/documents/{document_id}")
def document_detail_page(document_id: uuid.UUID, request: Request, db: Session = Depends(get_db)):
    document = db.get(Document, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="document not found")
    ai_outputs = (
        db.query(AiOutput)
        .filter(AiOutput.input_ref_type == "document", AiOutput.input_ref_id == document_id)
        .order_by(AiOutput.created_at.desc())
        .all()
    )
    link_rows = db.query(IssueLink).filter(IssueLink.document_id == document_id).all()
    issue_links = [(link, db.get(Issue, link.issue_id)) for link in link_rows]
    issue_links = [(link, issue) for link, issue in issue_links if issue is not None]
    all_issues = db.query(Issue).order_by(Issue.title).all()
    suggested_issues = suggest_issues_for_document(db, document)
    return templates.TemplateResponse(
        "document_detail.html",
        {
            "request": request,
            "document": document,
            "ai_outputs": ai_outputs,
            "issue_links": issue_links,
            "all_issues": all_issues,
            "suggested_issues": suggested_issues,
        },
    )


@router.post("/documents/{document_id}/classify")
def classify_document_form(document_id: uuid.UUID, db: Session = Depends(get_db)):
    document = db.get(Document, document_id)
    if document:
        classify_document(db, document)
    return RedirectResponse(url=f"/documents/{document_id}", status_code=303)


@router.post("/documents/{document_id}/ai-outputs/{output_id}/acknowledge")
def acknowledge_ai_output_form(
    document_id: uuid.UUID,
    output_id: uuid.UUID,
    operator_note: str = Form(""),
    db: Session = Depends(get_db),
):
    output = db.get(AiOutput, output_id)
    if output and output.input_ref_id == document_id:
        output.reviewed = True
        if operator_note:
            output.operator_note = operator_note
        db.commit()
    return RedirectResponse(url=f"/documents/{document_id}", status_code=303)


@router.post("/documents/{document_id}/attach-issue")
def attach_issue_form(document_id: uuid.UUID, issue_id: uuid.UUID = Form(...), db: Session = Depends(get_db)):
    existing = (
        db.query(IssueLink)
        .filter(IssueLink.document_id == document_id, IssueLink.issue_id == issue_id)
        .one_or_none()
    )
    if not existing:
        db.add(
            IssueLink(
                issue_id=issue_id,
                document_id=document_id,
                relationship_type="manual",
                confidence="operator",
                created_by="operator",
            )
        )
        db.commit()
    return RedirectResponse(url=f"/documents/{document_id}", status_code=303)


@router.get("/manual-submissions/new")
def manual_submission_form_page(request: Request):
    return templates.TemplateResponse("manual_submission_form.html", {"request": request})


@router.post("/manual-submissions/new")
def create_manual_submission_form(
    submission_type: str = Form(...),
    claimed_source: str = Form(""),
    content_text: str = Form(""),
    content_url: str = Form(""),
    operator_note: str = Form(""),
    db: Session = Depends(get_db),
):
    db.add(
        ManualSubmission(
            submission_type=submission_type,
            claimed_source=claimed_source or None,
            content_text=content_text or None,
            content_url=content_url or None,
            operator_note=operator_note or None,
            verified=False,
            verification_status="unresolved",
        )
    )
    db.commit()
    return RedirectResponse(url="/review-queue", status_code=303)
