"""Read-only API (PRD "Minimal read API"). Operator mutations (create/
revise/review) go through service.py directly for now -- no dashboard UI
yet, per this PR's explicitly reduced scope (see docs/organization-tracker/
MVP-PRD.md and the implementation note in this package's README).
"""

import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Entity
from app.organization_tracker.models import (
    OrganizationVersion,
    OrgEvent,
    OrgRelationship,
    OrgSourceAssertion,
    PositionVersion,
    UnitVersion,
)
from app.organization_tracker.schemas import (
    EntityOut,
    OrganizationOut,
    OrganizationStructureOut,
    OrgEventOut,
    OrgSourceAssertionOut,
    PositionOut,
    UnitOut,
)

router = APIRouter(prefix="/api", tags=["organization-tracker"])


def _entity_out(entity: Entity) -> EntityOut:
    return EntityOut(
        id=str(entity.id), entity_type=entity.entity_type, canonical_name=entity.canonical_name, aliases=entity.aliases
    )


def _organization_out(entity: Entity, version: OrganizationVersion) -> OrganizationOut:
    return OrganizationOut(
        id=str(entity.id),
        entity_type=entity.entity_type,
        canonical_name=entity.canonical_name,
        aliases=entity.aliases,
        org_type=version.org_type,
        jurisdiction=version.jurisdiction,
        status=version.status,
        valid_from=version.valid_from,
        valid_to=version.valid_to,
    )


def _current_or_as_of(query, model, as_of: date | None):
    """as_of=None means "current" -- valid_to IS NULL. Otherwise the
    version whose [valid_from, valid_to) window contains as_of.
    """
    if as_of is None:
        return query.filter(model.valid_to.is_(None))
    return query.filter(
        model.valid_from <= as_of, (model.valid_to.is_(None)) | (model.valid_to > as_of)
    )


@router.get("/organizations", response_model=list[OrganizationOut])
def list_organizations(db: Session = Depends(get_db)) -> list[OrganizationOut]:
    rows = (
        _current_or_as_of(db.query(Entity, OrganizationVersion), OrganizationVersion, None)
        .join(OrganizationVersion, OrganizationVersion.entity_id == Entity.id)
        .filter(Entity.entity_type == "organization")
        .all()
    )
    return [_organization_out(entity, version) for entity, version in rows]


@router.get("/organizations/{entity_id}", response_model=OrganizationOut)
def get_organization(entity_id: uuid.UUID, db: Session = Depends(get_db)) -> OrganizationOut:
    entity = db.get(Entity, entity_id)
    if not entity or entity.entity_type != "organization":
        raise HTTPException(status_code=404, detail="organization not found")
    version = (
        db.query(OrganizationVersion)
        .filter(OrganizationVersion.entity_id == entity_id, OrganizationVersion.valid_to.is_(None))
        .one_or_none()
    )
    if not version:
        raise HTTPException(status_code=404, detail="organization has no current version")
    return _organization_out(entity, version)


@router.get("/organizations/{entity_id}/structure", response_model=OrganizationStructureOut)
def get_organization_structure(
    entity_id: uuid.UUID, at: date | None = None, db: Session = Depends(get_db)
) -> OrganizationStructureOut:
    entity = db.get(Entity, entity_id)
    if not entity or entity.entity_type != "organization":
        raise HTTPException(status_code=404, detail="organization not found")
    org_version = _current_or_as_of(
        db.query(OrganizationVersion).filter(OrganizationVersion.entity_id == entity_id), OrganizationVersion, at
    ).one_or_none()
    if not org_version:
        raise HTTPException(status_code=404, detail="organization has no version as of that date")

    unit_rows = _current_or_as_of(
        db.query(Entity, UnitVersion).join(UnitVersion, UnitVersion.entity_id == Entity.id).filter(
            UnitVersion.organization_entity_id == entity_id
        ),
        UnitVersion,
        at,
    ).all()
    units = [
        UnitOut(
            id=str(e.id), entity_type=e.entity_type, canonical_name=e.canonical_name, aliases=e.aliases,
            organization_entity_id=str(v.organization_entity_id), unit_type=v.unit_type,
            parent_unit_entity_id=str(v.parent_unit_entity_id) if v.parent_unit_entity_id else None,
            status=v.status, valid_from=v.valid_from, valid_to=v.valid_to,
        )
        for e, v in unit_rows
    ]

    position_rows = _current_or_as_of(
        db.query(Entity, PositionVersion).join(PositionVersion, PositionVersion.entity_id == Entity.id).filter(
            PositionVersion.organization_entity_id == entity_id
        ),
        PositionVersion,
        at,
    ).all()
    positions = []
    for e, v in position_rows:
        occupant_rows = _current_or_as_of(
            db.query(Entity)
            .join(OrgRelationship, OrgRelationship.subject_entity_id == Entity.id)
            .filter(OrgRelationship.relationship_type == "occupies_position", OrgRelationship.object_entity_id == e.id),
            OrgRelationship,
            at,
        ).all()
        positions.append(
            PositionOut(
                id=str(e.id), entity_type=e.entity_type, canonical_name=e.canonical_name, aliases=e.aliases,
                organization_entity_id=str(v.organization_entity_id),
                unit_entity_id=str(v.unit_entity_id) if v.unit_entity_id else None,
                title=v.title, position_type=v.position_type, status=v.status,
                authorized_count=v.authorized_count, valid_from=v.valid_from, valid_to=v.valid_to,
                occupants=[_entity_out(o) for o in occupant_rows],
            )
        )

    return OrganizationStructureOut(
        as_of=at or date.today(),
        organization=_organization_out(entity, org_version),
        units=units,
        positions=positions,
    )


@router.get("/organizations/{entity_id}/events", response_model=list[OrgEventOut])
def get_organization_events(entity_id: uuid.UUID, db: Session = Depends(get_db)) -> list[OrgEventOut]:
    rows = (
        db.query(OrgEvent)
        .filter(OrgEvent.organization_entity_id == entity_id)
        .order_by(OrgEvent.observed_date.desc())
        .all()
    )
    return [_event_out(e) for e in rows]


def _event_out(e: OrgEvent) -> OrgEventOut:
    return OrgEventOut(
        id=str(e.id), organization_entity_id=str(e.organization_entity_id), event_type=e.event_type,
        effective_date=e.effective_date, observed_date=e.observed_date, title=e.title, narrative=e.narrative,
        certainty=e.certainty, review_status=e.review_status, reviewer_note=e.reviewer_note,
        created_at=e.created_at, reviewed_at=e.reviewed_at,
    )


@router.get("/units/{entity_id}", response_model=UnitOut)
def get_unit(entity_id: uuid.UUID, db: Session = Depends(get_db)) -> UnitOut:
    entity = db.get(Entity, entity_id)
    if not entity or entity.entity_type != "organizational_unit":
        raise HTTPException(status_code=404, detail="unit not found")
    v = (
        db.query(UnitVersion)
        .filter(UnitVersion.entity_id == entity_id, UnitVersion.valid_to.is_(None))
        .one_or_none()
    )
    if not v:
        raise HTTPException(status_code=404, detail="unit has no current version")
    return UnitOut(
        id=str(entity.id), entity_type=entity.entity_type, canonical_name=entity.canonical_name,
        aliases=entity.aliases, organization_entity_id=str(v.organization_entity_id), unit_type=v.unit_type,
        parent_unit_entity_id=str(v.parent_unit_entity_id) if v.parent_unit_entity_id else None,
        status=v.status, valid_from=v.valid_from, valid_to=v.valid_to,
    )


@router.get("/positions/{entity_id}", response_model=PositionOut)
def get_position(entity_id: uuid.UUID, db: Session = Depends(get_db)) -> PositionOut:
    entity = db.get(Entity, entity_id)
    if not entity or entity.entity_type != "position":
        raise HTTPException(status_code=404, detail="position not found")
    v = (
        db.query(PositionVersion)
        .filter(PositionVersion.entity_id == entity_id, PositionVersion.valid_to.is_(None))
        .one_or_none()
    )
    if not v:
        raise HTTPException(status_code=404, detail="position has no current version")
    occupants = (
        db.query(Entity)
        .join(OrgRelationship, OrgRelationship.subject_entity_id == Entity.id)
        .filter(
            OrgRelationship.relationship_type == "occupies_position",
            OrgRelationship.object_entity_id == entity_id,
            OrgRelationship.valid_to.is_(None),
        )
        .all()
    )
    return PositionOut(
        id=str(entity.id), entity_type=entity.entity_type, canonical_name=entity.canonical_name,
        aliases=entity.aliases, organization_entity_id=str(v.organization_entity_id),
        unit_entity_id=str(v.unit_entity_id) if v.unit_entity_id else None, title=v.title,
        position_type=v.position_type, status=v.status, authorized_count=v.authorized_count,
        valid_from=v.valid_from, valid_to=v.valid_to, occupants=[_entity_out(o) for o in occupants],
    )


@router.get("/people/{entity_id}", response_model=EntityOut)
def get_person(entity_id: uuid.UUID, db: Session = Depends(get_db)) -> EntityOut:
    entity = db.get(Entity, entity_id)
    if not entity or entity.entity_type != "person":
        raise HTTPException(status_code=404, detail="person not found")
    return _entity_out(entity)


@router.get("/organization-assertions/{assertion_id}", response_model=OrgSourceAssertionOut)
def get_assertion(assertion_id: uuid.UUID, db: Session = Depends(get_db)) -> OrgSourceAssertionOut:
    a = db.get(OrgSourceAssertion, assertion_id)
    if not a:
        raise HTTPException(status_code=404, detail="assertion not found")
    return OrgSourceAssertionOut(
        id=str(a.id), document_id=str(a.document_id), subject_text=a.subject_text,
        subject_entity_id=str(a.subject_entity_id) if a.subject_entity_id else None, predicate=a.predicate,
        object_text=a.object_text, object_entity_id=str(a.object_entity_id) if a.object_entity_id else None,
        assertion_type=a.assertion_type, effective_date=a.effective_date, observed_at=a.observed_at,
        evidence_mode=a.evidence_mode, source_authority=a.source_authority, extraction_method=a.extraction_method,
        confidence=a.confidence, review_status=a.review_status,
        superseded_assertion_id=str(a.superseded_assertion_id) if a.superseded_assertion_id else None,
    )
