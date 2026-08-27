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
    positions = []
    for pos_entity, version in position_rows:
        occupants = service.current_occupants(db, pos_entity.id, at)
        positions.append({"entity": pos_entity, "version": version, "occupants": occupants})

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


@router.get("/organizations/{entity_id}/review")
def organization_review_page(entity_id: uuid.UUID, request: Request, db: Session = Depends(get_db)):
    entity = db.get(Entity, entity_id)
    events = (
        db.query(OrgEvent)
        .filter(OrgEvent.organization_entity_id == entity_id, OrgEvent.review_status == "pending")
        .order_by(OrgEvent.observed_date.desc())
        .all()
    )
    event_context = []
    for event in events:
        assertion_ids = [
            r.assertion_id for r in db.query(OrgEventAssertion).filter(OrgEventAssertion.event_id == event.id).all()
        ]
        assertions = db.query(OrgSourceAssertion).filter(OrgSourceAssertion.id.in_(assertion_ids)).all() if assertion_ids else []
        entity_ids = [
            r.entity_id for r in db.query(OrgEventEntity).filter(OrgEventEntity.event_id == event.id).all()
        ]
        affected = db.query(Entity).filter(Entity.id.in_(entity_ids)).all() if entity_ids else []
        event_context.append({"event": event, "assertions": assertions, "affected": affected})

    return templates.TemplateResponse(
        "organization_review.html", {"request": request, "entity": entity, "event_context": event_context}
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
