"""Orchestrates the read-only-until-review half of the PRD's pipeline for
one document: extract candidate assertions, then draft an event for each
one reconciliation says is new or conflicting. Nothing here writes to
accepted state (org_relationships, *_versions) -- only assertions and
*proposed*, unreviewed events. See event_drafting.py's docstring for why
a CONFIRMING/DUPLICATING/UNRESOLVED assertion drafts nothing.

run_batch() is worker.py's hook (see app/worker.py's run_organization_tracker_batch)
-- it's deliberately jurisdiction-agnostic, matching a document to a
tracked organization by Document.jurisdiction == OrganizationVersion.jurisdiction
rather than any Ventura-specific check, so a city with no organizations
seeded yet (Santa Cruz, Boston -- Organization Tracker is Ventura-MVP-scoped
by seed data, not by code) just no-ops safely.
"""

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import exists
from sqlalchemy.orm import Session

from app.models import Document, Entity
from app.organization_tracker import event_drafting, extraction
from app.organization_tracker.models import (
    OrganizationVersion,
    OrgDocumentProcessing,
    OrgEvent,
    OrgSourceAssertion,
)

logger = logging.getLogger(__name__)

BATCH_SIZE = 25


@dataclass
class DocumentProcessingResult:
    assertions: list[OrgSourceAssertion] = field(default_factory=list)
    drafted_events: list[OrgEvent] = field(default_factory=list)


def process_document_for_organization(
    db: Session, document: Document, organization_entity_id: uuid.UUID
) -> DocumentProcessingResult:
    assertions = extraction.extract_assertions_from_document(db, document)
    drafted_events = []
    for assertion in assertions:
        event = event_drafting.draft_event_from_assertion(db, assertion, organization_entity_id)
        if event is not None:
            drafted_events.append(event)
    return DocumentProcessingResult(assertions=assertions, drafted_events=drafted_events)


def run_batch(db: Session) -> None:
    """Processes up to BATCH_SIZE not-yet-processed parsed documents per
    call, matching each to every currently-tracked organization sharing
    its jurisdiction. Marks a document processed (OrgDocumentProcessing)
    even if zero organizations matched or zero assertions were extracted
    -- both are valid final outcomes, not something to retry every tick.
    """
    organizations = (
        db.query(Entity, OrganizationVersion)
        .join(OrganizationVersion, OrganizationVersion.entity_id == Entity.id)
        .filter(Entity.entity_type == "organization", OrganizationVersion.valid_to.is_(None))
        .all()
    )
    if not organizations:
        return  # nothing tracked in this city yet -- safe no-op, not an error

    already_processed = exists().where(OrgDocumentProcessing.document_id == Document.id)
    candidates = (
        db.query(Document)
        .filter(Document.parser_status == "parsed", ~already_processed)
        .limit(BATCH_SIZE)
        .all()
    )
    for document in candidates:
        matched = [
            entity for entity, version in organizations
            if version.jurisdiction and document.jurisdiction and version.jurisdiction == document.jurisdiction
        ]
        try:
            assertions_created = 0
            events_drafted = 0
            for entity in matched:
                result = process_document_for_organization(db, document, entity.id)
                assertions_created += len(result.assertions)
                events_drafted += len(result.drafted_events)
            db.add(
                OrgDocumentProcessing(
                    document_id=document.id,
                    processed_at=datetime.now(timezone.utc),
                    organizations_matched=len(matched),
                    assertions_created=assertions_created,
                    events_drafted=events_drafted,
                )
            )
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("organization tracker batch crashed for document %s", document.id)
