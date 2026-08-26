"""Entity resolution (PRD "Entity resolution"): matching an assertion's
free-text subject/object to an existing `entities` row before falling back
to creating a new one.

Implements the PRD's first two deterministic tiers only -- stable source
identifier (not applicable yet: no external ID feed exists to key off of)
and accepted alias/exact normalized identity. The third tier ("high-
confidence contextual match requiring review") is inherently fuzzy/
AI-adjacent and is deferred, same as issue_matching.py's embedding-based
suggestions elsewhere in this codebase -- resolve_entity returning None
here means "no confident match," not "no match is possible," and the
caller (extraction/reconciliation) decides whether to propose a new
candidate entity or leave the assertion unresolved for a human to match.
"""

import re
import uuid

from sqlalchemy.orm import Session

from app.models import Entity


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def resolve_entity(db: Session, text: str, entity_type: str) -> Entity | None:
    normalized = _normalize(text)
    if not normalized:
        return None

    candidates = db.query(Entity).filter(Entity.entity_type == entity_type).all()

    # Exact normalized canonical-name match first.
    for entity in candidates:
        if _normalize(entity.canonical_name) == normalized:
            return entity

    # Then accepted aliases.
    for entity in candidates:
        for alias in entity.aliases or []:
            if _normalize(alias) == normalized:
                return entity

    return None


def resolve_entity_id(db: Session, text: str | None, entity_type: str) -> uuid.UUID | None:
    if not text:
        return None
    entity = resolve_entity(db, text, entity_type)
    return entity.id if entity else None
