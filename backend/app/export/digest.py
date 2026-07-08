"""Daily digest rollup (prd.md 9.9.4, 15.1 step 7 "Draft daily internal digest").

Pure rollup over already-generated data -- no new AI calls here. Every item
surfaced was already classified/summarized at ingestion time with prompts
that frame facts vs. inference (prd.md 9.9.4 acceptance criteria #2); the
digest just groups that existing output by recency/urgency. Internal/draft by
design: prd.md 25 (open questions) leaves "emailed vs. shown in dashboard"
(#6) unresolved -- this renders in the dashboard only, since there's no email
infrastructure in this project and Phase 1 is LAN-only anyway. Nothing here
is ever auto-published (prd.md 9.9.4 acceptance criteria #3).
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models import AgendaItem, AiOutput, Alert, Document, ManualSubmission, Meeting

DEFAULT_WINDOW_HOURS = 24
DEFAULT_UPCOMING_DAYS = 14
DEFAULT_DEADLINE_DAYS = 14
SECTION_LIMIT = 20


def build_daily_digest(db: Session, window_hours: int = DEFAULT_WINDOW_HOURS) -> dict:
    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=window_hours)
    upcoming_until = now + timedelta(days=DEFAULT_UPCOMING_DAYS)
    deadline_until = (now + timedelta(days=DEFAULT_DEADLINE_DAYS)).date()

    top_changes = (
        db.query(Alert)
        .filter(Alert.created_at >= since, Alert.alert_level >= 3)
        .order_by(Alert.alert_level.desc(), Alert.created_at.desc())
        .limit(SECTION_LIMIT)
        .all()
    )

    upcoming_hearings = (
        db.query(AgendaItem, Meeting)
        .join(Meeting, Meeting.id == AgendaItem.meeting_id)
        .filter(
            Meeting.start_time.between(now, upcoming_until),
            (AgendaItem.public_hearing.is_(True)) | (AgendaItem.vote_expected.is_(True)),
        )
        .order_by(Meeting.start_time.asc())
        .limit(SECTION_LIMIT)
        .all()
    )

    new_notices = (
        db.query(Document)
        .filter(Document.created_at >= since, Document.document_type == "notice")
        .order_by(Document.created_at.desc())
        .limit(SECTION_LIMIT)
        .all()
    )

    new_campaign_items = (
        db.query(Document)
        .filter(Document.created_at >= since, Document.agency == "Elections / Campaign Finance")
        .order_by(Document.created_at.desc())
        .limit(SECTION_LIMIT)
        .all()
    )

    needs_review = (
        db.query(AiOutput, Document)
        .join(Document, Document.id == AiOutput.input_ref_id)
        .filter(
            AiOutput.created_at >= since,
            AiOutput.task_type == "classification",
            AiOutput.output_json["human_review_required"].astext == "true",
        )
        .order_by(AiOutput.created_at.desc())
        .limit(SECTION_LIMIT)
        .all()
    )

    approaching_deadlines = (
        db.query(Document)
        .filter(
            Document.comment_deadline.isnot(None),
            Document.comment_deadline <= deadline_until,
            Document.comment_deadline >= now.date(),
        )
        .order_by(Document.comment_deadline.asc())
        .limit(SECTION_LIMIT)
        .all()
    )

    low_confidence = (
        db.query(AiOutput, Document)
        .join(Document, Document.id == AiOutput.input_ref_id)
        .filter(
            AiOutput.created_at >= since,
            AiOutput.task_type == "classification",
            AiOutput.confidence == "low",
        )
        .order_by(AiOutput.created_at.desc())
        .limit(SECTION_LIMIT)
        .all()
    )
    unverified_submissions = (
        db.query(ManualSubmission)
        .filter(ManualSubmission.submitted_at >= since, ManualSubmission.verification_status == "unresolved")
        .order_by(ManualSubmission.submitted_at.desc())
        .all()
    )

    return {
        "generated_at": now,
        "window_hours": window_hours,
        "top_changes": top_changes,
        "upcoming_hearings": upcoming_hearings,
        "new_notices": new_notices,
        "new_campaign_items": new_campaign_items,
        "needs_review": needs_review,
        "approaching_deadlines": approaching_deadlines,
        "low_confidence": low_confidence,
        "unverified_submissions": unverified_submissions,
    }


def render_digest_markdown(digest: dict) -> str:
    lines: list[str] = []
    generated = digest["generated_at"]
    lines.append(f"# Daily Digest — {generated.date().isoformat()}")
    lines.append("")
    lines.append(
        f"_Internal draft, generated {generated.isoformat()} covering the last "
        f"{digest['window_hours']}h. Not for public use — see prd.md 9.9.4/9.15._"
    )
    lines.append("")

    lines.append("## Top Changes")
    lines.append("")
    if digest["top_changes"]:
        for alert in digest["top_changes"]:
            lines.append(f"- **L{alert.alert_level}** {alert.title} — {alert.trigger_reason or alert.summary or ''}")
    else:
        lines.append("_No level 3+ alerts in this window._")
    lines.append("")

    lines.append("## Upcoming Hearings and Votes")
    lines.append("")
    if digest["upcoming_hearings"]:
        for item, meeting in digest["upcoming_hearings"]:
            when = meeting.start_time.date().isoformat() if meeting.start_time else "date unknown"
            kind = "hearing" if item.public_hearing else "vote"
            lines.append(f"- {when} ({kind}): [{item.title}](/agenda-items/{item.id}) — {meeting.body}")
    else:
        lines.append("_None scheduled in the next 14 days._")
    lines.append("")

    lines.append("## New Public Notices")
    lines.append("")
    if digest["new_notices"]:
        for doc in digest["new_notices"]:
            lines.append(f"- [{doc.title or '(untitled)'}]({doc.original_url or doc.archive_path})")
    else:
        lines.append("_None in this window._")
    lines.append("")

    lines.append("## New Campaign/Election Items")
    lines.append("")
    if digest["new_campaign_items"]:
        for doc in digest["new_campaign_items"]:
            lines.append(f"- [{doc.title or '(untitled)'}]({doc.original_url or doc.archive_path})")
    else:
        lines.append("_None in this window._")
    lines.append("")

    lines.append("## Items Needing Human Review")
    lines.append("")
    if digest["needs_review"]:
        for _, doc in digest["needs_review"]:
            lines.append(f"- [{doc.title or '(untitled)'}](/documents/{doc.id})")
    else:
        lines.append("_None flagged in this window._")
    lines.append("")

    lines.append("## Items With Approaching Deadlines")
    lines.append("")
    if digest["approaching_deadlines"]:
        for doc in digest["approaching_deadlines"]:
            lines.append(f"- {doc.comment_deadline.isoformat()}: [{doc.title or '(untitled)'}](/documents/{doc.id})")
    else:
        lines.append("_None recorded (structured deadline extraction is limited today — see README known gaps)._")
    lines.append("")

    lines.append("## Low-Confidence or Unverified Claims")
    lines.append("")
    has_any = digest["low_confidence"] or digest["unverified_submissions"]
    if digest["low_confidence"]:
        for _, doc in digest["low_confidence"]:
            lines.append(f"- (low-confidence classification) [{doc.title or '(untitled)'}](/documents/{doc.id})")
    if digest["unverified_submissions"]:
        for sub in digest["unverified_submissions"]:
            lines.append(f"- (unverified submission) {sub.claimed_source or 'unknown source'}: {sub.content_text[:120] if sub.content_text else ''}")
    if not has_any:
        lines.append("_None in this window._")
    lines.append("")

    lines.append("---")
    lines.append(
        "_Generated by Ventura Civic Radar from existing AI classifications/summaries — no new model calls. "
        "Distinguish source facts from AI inference per each linked item's own AI outputs; human review required "
        "before any public use._"
    )
    return "\n".join(lines)
