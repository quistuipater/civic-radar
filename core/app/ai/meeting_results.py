"""Summarizes what actually happened at a meeting, from its minutes --
outcomes/votes, not proposals (see app/ai/agenda_items.py for the agenda
side: "what's being proposed"). Deliberately does NOT try to match each
decision back to a specific agenda_items row: item numbering and formatting
drift too much between an agenda and its minutes to do that reliably without
a real trial run against actual minutes documents first (same lesson as the
72/80 false-positive rate that killed auto-linking in app/issue_matching.py)
-- this stores one meeting-level summary per minutes document instead,
surfaced via the existing generic ai_outputs display (no new UI needed).

No heuristic fallback, same reasoning as agenda_items.py: contextualizing
what happened at a meeting isn't something a keyword/regex pass can do
reliably -- this just waits for a later run if Ollama's unavailable.
"""

import logging

from sqlalchemy.orm import Session

from app.ai import ollama_client
from app.ai.classify import load_document_text
from app.config import settings
from app.models import AiOutput, Document, Prompt

logger = logging.getLogger(__name__)

MAX_CHARS = 12000


def extract_meeting_results(db: Session, document: Document) -> AiOutput | None:
    if document.document_type != "minutes":
        return None

    already_extracted = (
        db.query(AiOutput)
        .filter(
            AiOutput.input_ref_type == "document",
            AiOutput.input_ref_id == document.id,
            AiOutput.task_type == "meeting_results_summary",
        )
        .first()
    )
    if already_extracted:
        return already_extracted

    prompt_row = (
        db.query(Prompt)
        .filter(Prompt.prompt_key == "meeting_results_summary", Prompt.active.is_(True))
        .order_by(Prompt.created_at.desc())
        .first()
    )
    if prompt_row is None or not ollama_client.is_available():
        return None

    text = load_document_text(document)
    if not text.strip():
        return None

    prompt = prompt_row.prompt_text.format(
        project_name=settings.project_name,
        jurisdiction=document.jurisdiction or "",
        agency=document.agency or "",
        meeting_date=document.meeting_date or "",
        text=text[:MAX_CHARS],
    )
    output_json, error = ollama_client.generate_json(prompt_row.model_name, prompt, timeout=180.0)

    ai_output = AiOutput(
        task_type="meeting_results_summary",
        model_name=prompt_row.model_name if output_json is not None else "none",
        prompt_version=prompt_row.prompt_version,
        input_ref_type="document",
        input_ref_id=document.id,
        output_json=output_json,
        output_text=output_json.get("overall_summary") if output_json else None,
        confidence=output_json.get("source_confidence") if output_json else "none",
        error_message=error,
    )
    db.add(ai_output)
    db.commit()

    if output_json is None:
        logger.info("meeting results extraction failed for document %s: %s", document.id, error)
    else:
        logger.info(
            "extracted meeting results for document %s (%d decision(s))",
            document.id,
            len(output_json.get("key_decisions") or []),
        )
    return ai_output
