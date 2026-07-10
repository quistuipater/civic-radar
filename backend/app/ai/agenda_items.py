"""Splits an agenda document into individual agenda_items rows (prd.md 15.2,
9.9.2) -- the "no agenda-item-level extraction" Phase 0 gap. Only meaningful
for document_type == "agenda" documents that are linked to a Meeting (via
Meeting.agenda_document_id, populated at ingestion time). There's no
heuristic fallback here (unlike classification) since structural splitting
without a model isn't something a keyword/regex pass can do reliably -- if
Ollama is unavailable this just waits for a later run.
"""

import logging

from sqlalchemy.orm import Session

from app.ai import ollama_client
from app.ai.classify import load_document_text
from app.models import AgendaItem, AiOutput, Document, Meeting, Prompt

logger = logging.getLogger(__name__)

MAX_CHARS = 12000
ACTION_TYPES = {"consent", "discussion", "action", "public_hearing", "presentation", "closed_session"}


def extract_agenda_items(db: Session, document: Document) -> None:
    if document.document_type != "agenda":
        return

    meeting = db.query(Meeting).filter(Meeting.agenda_document_id == document.id).one_or_none()
    if meeting is None:
        return

    already_extracted = db.query(AgendaItem).filter(AgendaItem.meeting_id == meeting.id).first()
    if already_extracted:
        return

    prompt_row = (
        db.query(Prompt)
        .filter(Prompt.prompt_key == "agenda_item_extraction", Prompt.active.is_(True))
        .order_by(Prompt.created_at.desc())
        .first()
    )
    if prompt_row is None or not ollama_client.is_available():
        return

    text = load_document_text(document)
    if not text.strip():
        return

    prompt = prompt_row.prompt_text.format(
        jurisdiction=document.jurisdiction or "",
        agency=document.agency or "",
        meeting_date=document.meeting_date or "",
        text=text[:MAX_CHARS],
    )
    output_json, error = ollama_client.generate_json(prompt_row.model_name, prompt, timeout=180.0)

    db.add(
        AiOutput(
            task_type="agenda_item_extraction",
            model_name=prompt_row.model_name if output_json is not None else "none",
            prompt_version=prompt_row.prompt_version,
            input_ref_type="document",
            input_ref_id=document.id,
            output_json=output_json,
            error_message=error,
        )
    )

    if output_json is None:
        logger.info("agenda item extraction failed for document %s: %s", document.id, error)
        db.commit()
        return

    items = output_json.get("items") if isinstance(output_json, dict) else None
    if not isinstance(items, list):
        logger.warning("agenda item extraction returned unexpected shape for document %s", document.id)
        db.commit()
        return

    created = 0
    for raw in items:
        if not isinstance(raw, dict) or not raw.get("title"):
            continue
        action_type = raw.get("action_type")
        if action_type not in ACTION_TYPES:
            action_type = None
        db.add(
            AgendaItem(
                meeting_id=meeting.id,
                item_number=str(raw["item_number"]) if raw.get("item_number") is not None else None,
                title=str(raw["title"])[:2000],
                description=raw.get("description"),
                department=raw.get("department"),
                staff_recommendation=raw.get("staff_recommendation"),
                action_type=action_type,
                consent_calendar=bool(raw.get("consent_calendar", False)),
                public_hearing=bool(raw.get("public_hearing", False)),
                vote_expected=bool(raw.get("vote_expected", False)),
            )
        )
        created += 1
    db.commit()
    logger.info("extracted %d agenda item(s) for meeting %s from document %s", created, meeting.id, document.id)
