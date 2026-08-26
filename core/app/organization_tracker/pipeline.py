"""Orchestrates the read-only-until-review half of the PRD's pipeline for
one document: extract candidate assertions, then draft an event for each
one reconciliation says is new or conflicting. Nothing here writes to
accepted state (org_relationships, *_versions) -- only assertions and
*proposed*, unreviewed events. See event_drafting.py's docstring for why
a CONFIRMING/DUPLICATING/UNRESOLVED assertion drafts nothing.

Not yet wired into worker.py as an ongoing pipeline step (see this
package's README's "Explicitly deferred" section) -- callable directly
today, e.g. from a script or a future dashboard action.
"""

import uuid
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.models import Document
from app.organization_tracker import event_drafting, extraction
from app.organization_tracker.models import OrgEvent, OrgSourceAssertion


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
