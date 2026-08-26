"""Event drafting (PRD "Event drafting"): turns a reconciled assertion into
a proposed, still-human-reviewed OrgEvent -- the last automated step before
an operator's own approve/edit/reject/defer action (service.review_event).

Deliberately conservative about *what kind* of event it drafts: an
assertion whose evidence_mode isn't "explicit" becomes an
"unexplained_state_change" event regardless of predicate, never a specific
personnel action (appointed/resigned/terminated/...) -- the PRD's "Source
facts and inference remain distinct" principle and this project's
AI-guardrail language ("never infer... unless directly source-supported")
both require that. A CONFIRMING/UNRESOLVED/DUPLICATING assertion drafts no
event at all: there's nothing new to review.
"""

import uuid

from sqlalchemy.orm import Session

from app.organization_tracker import reconciliation, service
from app.organization_tracker.models import OrgEvent, OrgSourceAssertion

# Only used when evidence_mode == "explicit" -- an ADDING assertion with
# weaker evidence always becomes "unexplained_state_change" instead (see
# module docstring), so this table never needs entries for personnel
# actions this pass can't distinguish (promoted vs. demoted vs. hired).
_EVENT_TYPE_BY_PREDICATE = {
    "occupies_position": "appointed",
    "member_of": "appointed",
    "reports_to_position": "reporting_relationship_changed",
    "unit_reports_to_unit": "reporting_relationship_changed",
    "appoints": "appointed",
    "oversees": "reporting_relationship_changed",
    "part_of": "reporting_relationship_changed",
    "succeeded_by": "reassigned",
}


def _event_type(assertion: OrgSourceAssertion, classification: str) -> str:
    if assertion.evidence_mode != "explicit":
        return "unexplained_state_change"
    if classification == reconciliation.CONTRADICTING and assertion.predicate == "occupies_position":
        return "reassigned"
    return _EVENT_TYPE_BY_PREDICATE.get(assertion.predicate, "state_change")


def _narrative(assertion: OrgSourceAssertion, classification: str, event_type: str) -> str:
    predicate_phrase = assertion.predicate.replace("_", " ")
    if event_type == "unexplained_state_change":
        return (
            f'Evidence indicates a possible change ("{predicate_phrase}": {assertion.subject_text} / '
            f'{assertion.object_text or "?"}) but the source does not explicitly state the underlying event. '
            f'Observed passage: "{assertion.quoted_passage or ""}". Unknown: the reason for the change, and '
            f"whether it reflects a real personnel/structural action or an unrelated page update."
        )
    base = f'{assertion.subject_text} {predicate_phrase} {assertion.object_text or ""}'.strip()
    if classification == reconciliation.CONTRADICTING:
        base += " (supersedes a previously accepted, different relationship)"
    if assertion.quoted_passage:
        base += f'. Source passage: "{assertion.quoted_passage}"'
    return base


def _title(assertion: OrgSourceAssertion, event_type: str) -> str:
    subject = assertion.subject_text
    obj = assertion.object_text or ""
    label = event_type.replace("_", " ")
    return f"{subject} — {label}{': ' + obj if obj else ''}"[:200]


def draft_event_from_assertion(
    db: Session, assertion: OrgSourceAssertion, organization_entity_id: uuid.UUID
) -> OrgEvent | None:
    """Returns None (drafts nothing) for CONFIRMING/DUPLICATING/UNRESOLVED
    assertions -- there's no new, reviewable change to propose. Caller
    supplies organization_entity_id since an assertion alone doesn't
    always carry enough context to derive which organization it belongs
    to (e.g. a bare person-to-person relationship).
    """
    result = reconciliation.classify_assertion(db, assertion)
    if result.classification in (reconciliation.CONFIRMING, reconciliation.DUPLICATING, reconciliation.UNRESOLVED):
        return None

    event_type = _event_type(assertion, result.classification)
    affected = [e for e in (assertion.subject_entity_id, assertion.object_entity_id) if e is not None]

    return service.propose_event(
        db,
        organization_entity_id=organization_entity_id,
        event_type=event_type,
        title=_title(assertion, event_type),
        narrative=_narrative(assertion, result.classification, event_type),
        certainty=assertion.confidence or "medium",
        observed_date=assertion.observed_at.date(),
        effective_date=assertion.effective_date,
        supporting_assertion_ids=[assertion.id],
        affected_entity_ids=affected,
    )
