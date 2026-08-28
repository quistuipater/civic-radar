"""HTML dashboard for Organization Tracker -- separate from routers.py's
JSON API (that stays read-only; this adds the operator review workflow
the PRD's "Review" section describes: approve/edit/reject/defer). Uses the
same shared Jinja2 template set as the rest of the dashboard (app/dashboard.py),
per the PRD's "may use... common templates" note in its implementation
boundary.
"""

import uuid
from datetime import date

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import Entity
from app.organization_tracker.models import (
    OrganizationVersion,
    OrgEvent,
    OrgEventAssertion,
    OrgEventEntity,
    OrgSourceAssertion,
    PositionVersion,
    UnitVersion,
)
from app.organization_tracker import service
from app.organization_tracker.routers import _current_or_as_of

router = APIRouter(tags=["organization-tracker-dashboard"])
templates = Jinja2Templates(directory="app/templates")
templates.env.globals["project_name"] = settings.project_name


@router.get("/organizations")
def organizations_list_page(request: Request, db: Session = Depends(get_db)):
    rows = (
        db.query(Entity, OrganizationVersion)
        .join(OrganizationVersion, OrganizationVersion.entity_id == Entity.id)
        .filter(Entity.entity_type == "organization", OrganizationVersion.valid_to.is_(None))
        .all()
    )
    pending_counts = {
        entity.id: db.query(OrgEvent).filter(
            OrgEvent.organization_entity_id == entity.id, OrgEvent.review_status == "pending"
        ).count()
        for entity, _ in rows
    }
    return templates.TemplateResponse(
        "organization_list.html", {"request": request, "organizations": rows, "pending_counts": pending_counts}
    )


@router.get("/organizations/{entity_id}")
def organization_detail_page(entity_id: uuid.UUID, request: Request, at: date | None = None, db: Session = Depends(get_db)):
    entity = db.get(Entity, entity_id)
    org_version = _current_or_as_of(
        db.query(OrganizationVersion).filter(OrganizationVersion.entity_id == entity_id), OrganizationVersion, at
    ).one_or_none()

    units = _current_or_as_of(
        db.query(Entity, UnitVersion).join(UnitVersion, UnitVersion.entity_id == Entity.id).filter(
            UnitVersion.organization_entity_id == entity_id
        ),
        UnitVersion,
        at,
    ).all()

    position_rows = _current_or_as_of(
        db.query(Entity, PositionVersion).join(PositionVersion, PositionVersion.entity_id == Entity.id).filter(
            PositionVersion.organization_entity_id == entity_id
        ),
        PositionVersion,
        at,
    ).all()
    unit_names_by_entity_id = {e.id: v.canonical_name for e, v in units}
    positions = []
    for pos_entity, version in position_rows:
        occupants = service.current_occupants(db, pos_entity.id, at)
        unit_name = unit_names_by_entity_id.get(version.unit_entity_id) if version.unit_entity_id else None
        positions.append({"entity": pos_entity, "version": version, "occupants": occupants, "unit_name": unit_name})

    pending_count = db.query(OrgEvent).filter(
        OrgEvent.organization_entity_id == entity_id, OrgEvent.review_status == "pending"
    ).count()

    return templates.TemplateResponse(
        "organization_detail.html",
        {
            "request": request,
            "entity": entity,
            "org_version": org_version,
            "units": units,
            "positions": positions,
            "as_of": at,
            "pending_count": pending_count,
        },
    )


def _event_context(db: Session, event: OrgEvent) -> dict:
    assertion_ids = [
        r.assertion_id for r in db.query(OrgEventAssertion).filter(OrgEventAssertion.event_id == event.id).all()
    ]
    assertions = (
        db.query(OrgSourceAssertion).filter(OrgSourceAssertion.id.in_(assertion_ids)).all() if assertion_ids else []
    )
    entity_ids = [r.entity_id for r in db.query(OrgEventEntity).filter(OrgEventEntity.event_id == event.id).all()]
    affected = db.query(Entity).filter(Entity.id.in_(entity_ids)).all() if entity_ids else []
    return {"event": event, "assertions": assertions, "affected": affected}


@router.get("/organizations/{entity_id}/review")
def organization_review_page(entity_id: uuid.UUID, request: Request, db: Session = Depends(get_db)):
    entity = db.get(Entity, entity_id)
    events = (
        db.query(OrgEvent)
        .filter(OrgEvent.organization_entity_id == entity_id, OrgEvent.review_status == "pending")
        .order_by(OrgEvent.observed_date.desc())
        .all()
    )
    event_context = [_event_context(db, event) for event in events]

    return templates.TemplateResponse(
        "organization_review.html", {"request": request, "entity": entity, "event_context": event_context}
    )


@router.get("/organizations/{entity_id}/changes")
def organization_changes_page(
    entity_id: uuid.UUID,
    request: Request,
    event_type: str = "",
    certainty: str = "",
    review_status: str = "",
    db: Session = Depends(get_db),
):
    """PRD "Change log": reviewed events (approved/rejected/deferred), not
    pending ones -- /review is where pending items live. Filterable by
    event type, certainty, and review status; each entry shows the
    evidence and, for an approved event, links to the relationship it
    created (routers.py's read endpoints already expose that -- no
    separate before/after snapshot table exists to diff against, so
    "before/after state" per the PRD is shown as "what changed and its
    current accepted state," not a stored snapshot pair).
    """
    entity = db.get(Entity, entity_id)
    query = db.query(OrgEvent).filter(
        OrgEvent.organization_entity_id == entity_id, OrgEvent.review_status != "pending"
    )
    if event_type:
        query = query.filter(OrgEvent.event_type == event_type)
    if certainty:
        query = query.filter(OrgEvent.certainty == certainty)
    if review_status:
        query = query.filter(OrgEvent.review_status == review_status)
    events = query.order_by(OrgEvent.observed_date.desc()).all()
    event_context = [_event_context(db, event) for event in events]

    event_types = [
        r[0] for r in db.query(OrgEvent.event_type).filter(OrgEvent.organization_entity_id == entity_id).distinct().all()
    ]

    return templates.TemplateResponse(
        "organization_changes.html",
        {
            "request": request,
            "entity": entity,
            "event_context": event_context,
            "event_types": event_types,
            "filters": {"event_type": event_type, "certainty": certainty, "review_status": review_status},
        },
    )


@router.get("/entities/{entity_id}")
def entity_detail_page(entity_id: uuid.UUID, request: Request, db: Session = Depends(get_db)):
    """PRD "Entity detail": accepted state, occupancy/membership history
    (open and closed relationships alike, not just the current one),
    associated events, and source assertions -- for one person, position,
    or unit, as opposed to /organizations/{id}'s whole-org structure view.
    """
    from app.organization_tracker.models import OrgRelationship

    entity = db.get(Entity, entity_id)

    as_subject = (
        db.query(OrgRelationship)
        .filter(OrgRelationship.subject_entity_id == entity_id)
        .order_by(OrgRelationship.valid_from.desc())
        .all()
    )
    as_object = (
        db.query(OrgRelationship)
        .filter(OrgRelationship.object_entity_id == entity_id)
        .order_by(OrgRelationship.valid_from.desc())
        .all()
    )
    other_ids = {r.object_entity_id for r in as_subject} | {r.subject_entity_id for r in as_object}
    other_entities = {e.id: e for e in db.query(Entity).filter(Entity.id.in_(other_ids)).all()} if other_ids else {}

    event_ids = [r.event_id for r in db.query(OrgEventEntity).filter(OrgEventEntity.entity_id == entity_id).all()]
    events = (
        db.query(OrgEvent).filter(OrgEvent.id.in_(event_ids)).order_by(OrgEvent.observed_date.desc()).all()
        if event_ids
        else []
    )

    assertions = (
        db.query(OrgSourceAssertion)
        .filter(
            (OrgSourceAssertion.subject_entity_id == entity_id) | (OrgSourceAssertion.object_entity_id == entity_id)
        )
        .order_by(OrgSourceAssertion.observed_at.desc())
        .limit(50)
        .all()
    )

    return templates.TemplateResponse(
        "entity_detail.html",
        {
            "request": request,
            "entity": entity,
            "as_subject": as_subject,
            "as_object": as_object,
            "other_entities": other_entities,
            "events": events,
            "assertions": assertions,
        },
    )


@router.post("/organizations/{entity_id}/events/{event_id}/review")
def review_event_form(
    entity_id: uuid.UUID,
    event_id: uuid.UUID,
    decision: str = Form(...),
    reviewer_note: str = Form(""),
    db: Session = Depends(get_db),
):
    service.review_event(db, event_id, decision, reviewer_note or None)
    return RedirectResponse(url=f"/organizations/{entity_id}/review", status_code=303)
