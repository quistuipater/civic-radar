"""Reconciliation (PRD "Reconciliation"): classifying a resolved assertion
against accepted state via deterministic comparison. Per the PRD, "AI may
explain or classify ambiguity but cannot accept it" -- nothing here calls
an AI model; it's a straight comparison against org_relationships.

Scoped to relationship-type assertions only (predicate values drawn from
the same vocabulary as OrgRelationship.relationship_type -- e.g.
"occupies_position", "member_of"). Reconciling a unit/position *attribute*
change (a rename, a status change) against its version history is a
distinct, not-yet-built case -- see this package's README.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.organization_tracker.models import OrgRelationship, OrgSourceAssertion

# Matches the PRD's classification taxonomy under "Reconciliation" --
# "supplying a missing date or explanation" is left out since nothing here
# yet detects that specific case (it would require comparing against an
# existing relationship's own null fields, not just presence/absence).
CONFIRMING = "confirming"
ADDING = "adding"
CONTRADICTING = "contradicting"
DUPLICATING = "duplicating"
UNRESOLVED = "unresolved"


@dataclass
class ReconciliationResult:
    classification: str
    # The currently-open relationship this assertion agrees or conflicts
    # with, if any -- None for ADDING/DUPLICATING/UNRESOLVED.
    conflicting_relationship_id: uuid.UUID | None = None


def classify_assertion(db: Session, assertion: OrgSourceAssertion) -> ReconciliationResult:
    if assertion.subject_entity_id is None or assertion.object_entity_id is None:
        return ReconciliationResult(UNRESOLVED)

    duplicate = (
        db.query(OrgSourceAssertion)
        .filter(
            OrgSourceAssertion.id != assertion.id,
            OrgSourceAssertion.document_id == assertion.document_id,
            OrgSourceAssertion.subject_entity_id == assertion.subject_entity_id,
            OrgSourceAssertion.predicate == assertion.predicate,
            OrgSourceAssertion.object_entity_id == assertion.object_entity_id,
        )
        .one_or_none()
    )
    if duplicate is not None:
        return ReconciliationResult(DUPLICATING)

    matching_open = (
        db.query(OrgRelationship)
        .filter(
            OrgRelationship.subject_entity_id == assertion.subject_entity_id,
            OrgRelationship.relationship_type == assertion.predicate,
            OrgRelationship.object_entity_id == assertion.object_entity_id,
            OrgRelationship.valid_to.is_(None),
        )
        .one_or_none()
    )
    if matching_open is not None:
        return ReconciliationResult(CONFIRMING, conflicting_relationship_id=matching_open.id)

    conflicting_open = (
        db.query(OrgRelationship)
        .filter(
            OrgRelationship.subject_entity_id == assertion.subject_entity_id,
            OrgRelationship.relationship_type == assertion.predicate,
            OrgRelationship.object_entity_id != assertion.object_entity_id,
            OrgRelationship.valid_to.is_(None),
        )
        .one_or_none()
    )
    if conflicting_open is not None:
        return ReconciliationResult(CONTRADICTING, conflicting_relationship_id=conflicting_open.id)

    return ReconciliationResult(ADDING)
