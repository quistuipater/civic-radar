"""Write path for Organization Tracker's data model (models.py).

Every mutation here follows the PRD's "current state never destroys
history": changing an attribute closes the currently-open version/
relationship (sets valid_to) and opens a new row, rather than UPDATEing a
value in place. Nothing here calls out to AI -- extraction/reconciliation
(turning a document into a proposed assertion, and an assertion into a
proposed event) is explicitly deferred; see docs/organization-tracker/
MVP-PRD.md's "Extraction and reconciliation" section. This module is the
foundation those steps would call, plus what an operator's own review
actions (approve/edit/reject/defer) exercise directly today.
"""

import uuid
from datetime import date, datetime, timezone

from sqlalchemy.orm import Session

from app.models import Entity
from app.organization_tracker.models import (
    OrganizationVersion,
    OrgEvent,
    OrgEventAssertion,
    OrgEventEntity,
    OrgRelationship,
    OrgSourceAssertion,
    PositionVersion,
    UnitVersion,
)


def _close_open(db: Session, model, entity_id: uuid.UUID, as_of: date) -> None:
    """Closes whichever version row for this entity currently has
    valid_to IS NULL, if any -- the precondition every "start a new
    version" helper below needs before inserting the replacement.
    """
    open_row = (
        db.query(model).filter(model.entity_id == entity_id, model.valid_to.is_(None)).one_or_none()
    )
    if open_row is not None:
        open_row.valid_to = as_of


def create_organization(
    db: Session,
    canonical_name: str,
    org_type: str,
    valid_from: date,
    jurisdiction: str | None = None,
    parent_entity_id: uuid.UUID | None = None,
    aliases: list[str] | None = None,
) -> Entity:
    entity = Entity(entity_type="organization", canonical_name=canonical_name, aliases=aliases)
    db.add(entity)
    db.flush()
    db.add(
        OrganizationVersion(
            entity_id=entity.id,
            org_type=org_type,
            parent_entity_id=parent_entity_id,
            jurisdiction=jurisdiction,
            valid_from=valid_from,
        )
    )
    db.commit()
    db.refresh(entity)
    return entity


def create_unit(
    db: Session,
    canonical_name: str,
    unit_type: str,
    organization_entity_id: uuid.UUID,
    valid_from: date,
    parent_unit_entity_id: uuid.UUID | None = None,
    aliases: list[str] | None = None,
) -> Entity:
    entity = Entity(entity_type="organizational_unit", canonical_name=canonical_name, aliases=aliases)
    db.add(entity)
    db.flush()
    db.add(
        UnitVersion(
            entity_id=entity.id,
            organization_entity_id=organization_entity_id,
            canonical_name=canonical_name,
            unit_type=unit_type,
            parent_unit_entity_id=parent_unit_entity_id,
            valid_from=valid_from,
        )
    )
    db.commit()
    db.refresh(entity)
    return entity


def rename_or_transfer_unit(
    db: Session,
    unit_entity_id: uuid.UUID,
    as_of: date,
    canonical_name: str | None = None,
    unit_type: str | None = None,
    parent_unit_entity_id: uuid.UUID | None = None,
    status: str | None = None,
) -> UnitVersion:
    """Closes the unit's current version and opens a new one carrying
    forward any field not explicitly overridden -- used for a rename,
    a reporting-line transfer, or a status change (active/dissolved/...),
    all of which are the same "new version" operation at this layer.
    """
    current = (
        db.query(UnitVersion)
        .filter(UnitVersion.entity_id == unit_entity_id, UnitVersion.valid_to.is_(None))
        .one()
    )
    _close_open(db, UnitVersion, unit_entity_id, as_of)
    new_version = UnitVersion(
        entity_id=unit_entity_id,
        organization_entity_id=current.organization_entity_id,
        canonical_name=canonical_name if canonical_name is not None else current.canonical_name,
        unit_type=unit_type if unit_type is not None else current.unit_type,
        parent_unit_entity_id=(
            parent_unit_entity_id if parent_unit_entity_id is not None else current.parent_unit_entity_id
        ),
        status=status if status is not None else current.status,
        valid_from=as_of,
    )
    db.add(new_version)
    db.commit()
    db.refresh(new_version)
    return new_version


def create_position(
    db: Session,
    title: str,
    position_type: str,
    organization_entity_id: uuid.UUID,
    valid_from: date,
    unit_entity_id: uuid.UUID | None = None,
    authorized_count: int | None = None,
) -> Entity:
    entity = Entity(entity_type="position", canonical_name=title)
    db.add(entity)
    db.flush()
    db.add(
        PositionVersion(
            entity_id=entity.id,
            organization_entity_id=organization_entity_id,
            unit_entity_id=unit_entity_id,
            title=title,
            position_type=position_type,
            authorized_count=authorized_count,
            valid_from=valid_from,
        )
    )
    db.commit()
    db.refresh(entity)
    return entity


def revise_position(
    db: Session,
    position_entity_id: uuid.UUID,
    as_of: date,
    title: str | None = None,
    unit_entity_id: uuid.UUID | None = None,
    status: str | None = None,
    authorized_count: int | None = None,
) -> PositionVersion:
    current = (
        db.query(PositionVersion)
        .filter(PositionVersion.entity_id == position_entity_id, PositionVersion.valid_to.is_(None))
        .one()
    )
    _close_open(db, PositionVersion, position_entity_id, as_of)
    new_version = PositionVersion(
        entity_id=position_entity_id,
        organization_entity_id=current.organization_entity_id,
        unit_entity_id=unit_entity_id if unit_entity_id is not None else current.unit_entity_id,
        title=title if title is not None else current.title,
        position_type=current.position_type,
        status=status if status is not None else current.status,
        authorized_count=(
            authorized_count if authorized_count is not None else current.authorized_count
        ),
        valid_from=as_of,
    )
    db.add(new_version)
    db.commit()
    db.refresh(new_version)
    return new_version


def create_person(db: Session, display_name: str, aliases: list[str] | None = None) -> Entity:
    entity = Entity(entity_type="person", canonical_name=display_name, aliases=aliases)
    db.add(entity)
    db.commit()
    db.refresh(entity)
    return entity


def start_relationship(
    db: Session,
    subject_entity_id: uuid.UUID,
    relationship_type: str,
    object_entity_id: uuid.UUID,
    valid_from: date,
) -> OrgRelationship:
    rel = OrgRelationship(
        subject_entity_id=subject_entity_id,
        relationship_type=relationship_type,
        object_entity_id=object_entity_id,
        valid_from=valid_from,
    )
    db.add(rel)
    db.commit()
    db.refresh(rel)
    return rel


def end_relationship(db: Session, relationship_id: uuid.UUID, valid_to: date) -> OrgRelationship:
    rel = db.get(OrgRelationship, relationship_id)
    rel.valid_to = valid_to
    db.commit()
    db.refresh(rel)
    return rel


def replace_relationship(
    db: Session,
    subject_entity_id: uuid.UUID,
    relationship_type: str,
    old_object_entity_id: uuid.UUID | None,
    new_object_entity_id: uuid.UUID,
    as_of: date,
) -> OrgRelationship:
    """Closes the open (subject, type, old_object) relationship, if one is
    given and found, and opens (subject, type, new_object) -- the common
    "new occupant of a position" / "new appointee" transition, kept as one
    call so both halves land in the same operator action.
    """
    if old_object_entity_id is not None:
        open_rel = (
            db.query(OrgRelationship)
            .filter(
                OrgRelationship.subject_entity_id == subject_entity_id,
                OrgRelationship.relationship_type == relationship_type,
                OrgRelationship.object_entity_id == old_object_entity_id,
                OrgRelationship.valid_to.is_(None),
            )
            .one_or_none()
        )
        if open_rel is not None:
            open_rel.valid_to = as_of
    return start_relationship(db, subject_entity_id, relationship_type, new_object_entity_id, as_of)


def record_assertion(
    db: Session,
    document_id: uuid.UUID,
    subject_text: str,
    predicate: str,
    assertion_type: str,
    evidence_mode: str,
    extraction_method: str,
    object_text: str | None = None,
    subject_entity_id: uuid.UUID | None = None,
    object_entity_id: uuid.UUID | None = None,
    effective_date: date | None = None,
    quoted_passage: str | None = None,
    source_authority: str | None = None,
    confidence: str | None = None,
    superseded_assertion_id: uuid.UUID | None = None,
    model_name: str | None = None,
    prompt_version: str | None = None,
    chunk_id: uuid.UUID | None = None,
    page_number: int | None = None,
) -> OrgSourceAssertion:
    if superseded_assertion_id is not None:
        superseded = db.get(OrgSourceAssertion, superseded_assertion_id)
        superseded.review_status = "superseded"
    assertion = OrgSourceAssertion(
        document_id=document_id,
        chunk_id=chunk_id,
        page_number=page_number,
        subject_text=subject_text,
        subject_entity_id=subject_entity_id,
        predicate=predicate,
        object_text=object_text,
        object_entity_id=object_entity_id,
        assertion_type=assertion_type,
        effective_date=effective_date,
        observed_at=datetime.now(timezone.utc),
        evidence_mode=evidence_mode,
        quoted_passage=quoted_passage,
        model_name=model_name,
        prompt_version=prompt_version,
        source_authority=source_authority,
        extraction_method=extraction_method,
        confidence=confidence,
        superseded_assertion_id=superseded_assertion_id,
    )
    db.add(assertion)
    db.commit()
    db.refresh(assertion)
    return assertion


def propose_event(
    db: Session,
    organization_entity_id: uuid.UUID,
    event_type: str,
    title: str,
    narrative: str,
    certainty: str,
    observed_date: date,
    effective_date: date | None = None,
    supporting_assertion_ids: list[uuid.UUID] | None = None,
    affected_entity_ids: list[uuid.UUID] | None = None,
) -> OrgEvent:
    event = OrgEvent(
        organization_entity_id=organization_entity_id,
        event_type=event_type,
        title=title,
        narrative=narrative,
        certainty=certainty,
        observed_date=observed_date,
        effective_date=effective_date,
    )
    db.add(event)
    db.flush()
    for assertion_id in supporting_assertion_ids or []:
        db.add(OrgEventAssertion(event_id=event.id, assertion_id=assertion_id))
    for entity_id in affected_entity_ids or []:
        db.add(OrgEventEntity(event_id=event.id, entity_id=entity_id))
    db.commit()
    db.refresh(event)
    return event


def review_event(
    db: Session, event_id: uuid.UUID, decision: str, reviewer_note: str | None = None
) -> OrgEvent:
    """decision: "approved" | "rejected" | "deferred" (PRD "Review": approve,
    edit, reject or defer). "approved" also applies the event's underlying
    relationship change to accepted state (see _apply_approved_event) --
    the PRD's "Acceptance is transactional: event, state transition...
    commit together" -- except "unexplained_state_change" events, which
    never auto-apply (approving one means "worth keeping on record," not
    "I know what actually happened"). "rejected"/"deferred" only touch the
    event's own review state.
    """
    if decision not in ("approved", "rejected", "deferred"):
        raise ValueError(f"invalid review decision: {decision}")
    event = db.get(OrgEvent, event_id)
    event.review_status = decision
    event.reviewer_note = reviewer_note
    event.reviewed_at = datetime.now(timezone.utc)
    if decision == "approved":
        _apply_approved_event(db, event)
    db.commit()
    db.refresh(event)
    return event


def _apply_approved_event(db: Session, event: OrgEvent) -> None:
    """Applies the state change an approved event represents -- the PRD's
    "Acceptance is transactional: event, state transition... commit
    together." Deliberately conservative: "unexplained_state_change"
    events never apply anything even on approval (approving one means
    "yes, this is worth keeping on record," not "yes, I know what
    actually happened" -- there's nothing concrete enough to apply). Only
    touches org_relationships, driven by the event's supporting
    assertions' resolved subject/predicate/object.
    """
    from app.organization_tracker.reconciliation import _SINGLE_OCCUPANT_PREDICATES

    if event.event_type == "unexplained_state_change":
        return

    links = db.query(OrgEventAssertion).filter(OrgEventAssertion.event_id == event.id).all()
    assertion_ids = [link.assertion_id for link in links]
    assertions = db.query(OrgSourceAssertion).filter(OrgSourceAssertion.id.in_(assertion_ids)).all()

    for assertion in assertions:
        if assertion.subject_entity_id is None or assertion.object_entity_id is None:
            continue
        effective = assertion.effective_date or event.effective_date or event.observed_date

        already_open = (
            db.query(OrgRelationship)
            .filter(
                OrgRelationship.subject_entity_id == assertion.subject_entity_id,
                OrgRelationship.relationship_type == assertion.predicate,
                OrgRelationship.object_entity_id == assertion.object_entity_id,
                OrgRelationship.valid_to.is_(None),
            )
            .first()
        )
        if already_open is not None:
            continue  # already accepted state (CONFIRMING) -- nothing to change

        # Subject-side supersede: this entity's other open relationship of
        # this type closes (e.g. moved from one position to another).
        db.query(OrgRelationship).filter(
            OrgRelationship.subject_entity_id == assertion.subject_entity_id,
            OrgRelationship.relationship_type == assertion.predicate,
            OrgRelationship.object_entity_id != assertion.object_entity_id,
            OrgRelationship.valid_to.is_(None),
        ).update({OrgRelationship.valid_to: effective}, synchronize_session=False)

        # Object-side supersede (succession), only for single-occupant predicates.
        if assertion.predicate in _SINGLE_OCCUPANT_PREDICATES:
            db.query(OrgRelationship).filter(
                OrgRelationship.object_entity_id == assertion.object_entity_id,
                OrgRelationship.relationship_type == assertion.predicate,
                OrgRelationship.subject_entity_id != assertion.subject_entity_id,
                OrgRelationship.valid_to.is_(None),
            ).update({OrgRelationship.valid_to: effective}, synchronize_session=False)

        db.add(
            OrgRelationship(
                subject_entity_id=assertion.subject_entity_id,
                relationship_type=assertion.predicate,
                object_entity_id=assertion.object_entity_id,
                valid_from=effective,
            )
        )


def current_occupants(db: Session, position_entity_id: uuid.UUID, as_of: date | None = None) -> list[Entity]:
    """Entities holding "occupies_position" against this position as of a
    date (None = today/current). A position persists independently of who
    holds it, so this is a relationship query, not a PositionVersion field.
    """
    query = db.query(Entity).join(OrgRelationship, OrgRelationship.subject_entity_id == Entity.id).filter(
        OrgRelationship.relationship_type == "occupies_position",
        OrgRelationship.object_entity_id == position_entity_id,
    )
    if as_of is None:
        query = query.filter(OrgRelationship.valid_to.is_(None))
    else:
        query = query.filter(
            OrgRelationship.valid_from <= as_of, (OrgRelationship.valid_to.is_(None)) | (OrgRelationship.valid_to > as_of)
        )
    return query.all()


def reporting_context(db: Session, position_entity_id: uuid.UUID, as_of: date | None = None) -> dict:
    """Who this position reports to (subject-side "reports_to_position") and
    who appointed it (object-side "appoints"), each as-of a date. Neither is
    guaranteed to exist -- most positions today have neither asserted.
    """

    def _open(query):
        if as_of is None:
            return query.filter(OrgRelationship.valid_to.is_(None))
        return query.filter(
            OrgRelationship.valid_from <= as_of, (OrgRelationship.valid_to.is_(None)) | (OrgRelationship.valid_to > as_of)
        )

    reports_to = _open(
        db.query(Entity)
        .join(OrgRelationship, OrgRelationship.object_entity_id == Entity.id)
        .filter(
            OrgRelationship.subject_entity_id == position_entity_id,
            OrgRelationship.relationship_type == "reports_to_position",
        )
    ).first()
    appointed_by = _open(
        db.query(Entity)
        .join(OrgRelationship, OrgRelationship.subject_entity_id == Entity.id)
        .filter(
            OrgRelationship.object_entity_id == position_entity_id,
            OrgRelationship.relationship_type == "appoints",
        )
    ).first()
    return {"reports_to": reports_to, "appointed_by": appointed_by}
