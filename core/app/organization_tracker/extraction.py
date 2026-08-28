"""Extraction (PRD "Candidate extraction"): turns a parsed document into
candidate org_source_assertions via the local AI layer, then resolves each
claim's subject/object text to an existing entity where possible (see
resolution.py). Mirrors app/ai/classify.py's pattern (Prompt row + Ollama,
degrades to nothing rather than a fabricated guess if the model or the
prompt row is unavailable).

Extraction alone never touches accepted state (org_relationships,
*_versions) -- it only creates OrgSourceAssertion rows. Turning an
assertion into a proposed event is reconciliation.py's and, ultimately, an
operator's job.
"""

import logging
from datetime import date, datetime

from sqlalchemy.orm import Session

from app.ai import ollama_client
from app.ai.classify import load_document_text
from app.models import Document, Prompt
from app.organization_tracker import resolution, service
from app.organization_tracker.models import OrgSourceAssertion

logger = logging.getLogger(__name__)

MAX_CHARS = 8000

# subject/object entity type is tried in this order until one resolves --
# see resolution.py's docstring for why this is a pragmatic heuristic
# rather than the real thing: extraction doesn't know a claim's entity
# type ahead of time, so it tries the most common case (a person's name)
# first, then organizational entities.
_RESOLUTION_ORDER = ("person", "position", "organizational_unit", "organization")


def _resolve_best_guess(db: Session, text: str | None):
    if not text:
        return None
    for entity_type in _RESOLUTION_ORDER:
        entity_id = resolution.resolve_entity_id(db, text, entity_type)
        if entity_id is not None:
            return entity_id
    return None


def _parse_date(raw: str | None) -> date | None:
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        return None


def extract_assertions_from_document(db: Session, document: Document) -> list[OrgSourceAssertion]:
    """Returns the newly created assertions (empty list if the prompt row
    or Ollama is unavailable, or the model found nothing/returned
    unparseable output) -- never raises, matching classify.py's contract
    so a bad document can't take down whatever calls this in a batch.
    """
    prompt_row = (
        db.query(Prompt)
        .filter(Prompt.prompt_key == "org_assertion_extraction", Prompt.active.is_(True))
        .order_by(Prompt.created_at.desc())
        .first()
    )
    if not prompt_row or not ollama_client.is_available():
        return []

    text = load_document_text(document)
    if not text.strip():
        return []

    prompt = prompt_row.prompt_text.format(
        project_name="Civic Radar",
        document_type=document.document_type or "",
        jurisdiction=document.jurisdiction or "",
        agency=document.agency or "",
        text=text[:MAX_CHARS],
    )
    output_json, error = ollama_client.generate_json(prompt_row.model_name, prompt, options=prompt_row.model_params)
    if error or not output_json:
        if error:
            logger.warning("org assertion extraction failed for document %s: %s", document.id, error)
        return []

    raw_assertions = output_json.get("assertions", [])
    if not isinstance(raw_assertions, list):
        return []

    created: list[OrgSourceAssertion] = []
    for item in raw_assertions:
        if not isinstance(item, dict):
            continue
        subject_text = item.get("subject_text")
        predicate = item.get("predicate")
        evidence_mode = item.get("evidence_mode")
        assertion_type = item.get("assertion_type")
        if not (subject_text and predicate and evidence_mode and assertion_type):
            continue  # incomplete row from the model -- skip rather than guess

        object_text = item.get("object_text")
        assertion = service.record_assertion(
            db,
            document_id=document.id,
            subject_text=subject_text,
            subject_entity_id=_resolve_best_guess(db, subject_text),
            predicate=predicate,
            object_text=object_text,
            object_entity_id=_resolve_best_guess(db, object_text),
            assertion_type=assertion_type,
            evidence_mode=evidence_mode,
            extraction_method="ai_ollama",
            effective_date=_parse_date(item.get("effective_date")),
            quoted_passage=item.get("quoted_passage"),
            confidence=item.get("confidence"),
            model_name=prompt_row.model_name,
            prompt_version=prompt_row.prompt_version,
            source_authority=document.agency,
        )
        created.append(assertion)
    return created
