"""Alert generation from a document's classification output (prd.md 9.12).

Alerts are deduplicated via a unique `dedup_key` so the same document/level
combination is never inserted twice — re-running the pipeline against an
already-classified document is a no-op here.
"""

from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import AiOutput, Alert, Document, Issue
from app.scoring import alert_level_for


def create_alert_from_classification(
    db: Session, document: Document, ai_output: AiOutput, issue: Issue | None = None
) -> Alert | None:
    output = ai_output.output_json or {}
    importance = int(output.get("importance_score", 0))
    urgency = int(output.get("urgency_score", 0))
    transparency = int(output.get("transparency_risk_score", 0))

    level = alert_level_for(importance, urgency, transparency, document.meeting_date)
    dedup_key = f"document:{document.id}:{level}"

    deadline = None
    for candidate in (document.comment_deadline, document.public_hearing_date, document.meeting_date):
        if candidate:
            deadline = datetime(candidate.year, candidate.month, candidate.day, tzinfo=timezone.utc)
            break

    trigger_bits = []
    if output.get("hearing_expected"):
        trigger_bits.append("hearing expected")
    if output.get("vote_expected"):
        trigger_bits.append("vote expected")
    if output.get("public_participation_opportunity"):
        trigger_bits.append("public comment opportunity")
    if transparency >= 6:
        trigger_bits.append("elevated transparency risk")
    trigger_reason = "; ".join(trigger_bits) or "routine classification"

    alert = Alert(
        issue_id=issue.id if issue else None,
        document_id=document.id,
        alert_level=level,
        title=document.title or f"New {document.document_type} — {document.body or document.agency}",
        summary=output.get("rationale"),
        trigger_reason=trigger_reason,
        deadline=deadline,
        dedup_key=dedup_key,
        reviewed=False,
    )
    db.add(alert)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return None
    return alert
