import logging

from sqlalchemy.orm import Session

from app.ai import ollama_client
from app.ai.classify import load_document_text
from app.models import AiOutput, Document, Prompt

logger = logging.getLogger(__name__)

MAX_CHARS = 8000


def summarize_document(db: Session, document: Document) -> AiOutput | None:
    prompt_row = (
        db.query(Prompt)
        .filter(Prompt.prompt_key == "document_summary", Prompt.active.is_(True))
        .order_by(Prompt.created_at.desc())
        .first()
    )
    if prompt_row is None:
        return None

    text = load_document_text(document)
    if not text.strip():
        return None

    output_json: dict | None = None
    error: str | None = None
    if ollama_client.is_available():
        prompt = prompt_row.prompt_text.format(
            title=document.title or "",
            jurisdiction=document.jurisdiction or "",
            text=text[:MAX_CHARS],
        )
        output_json, error = ollama_client.generate_json(prompt_row.model_name, prompt)
    else:
        error = "ollama unavailable; no summary generated (Phase 0 has no non-AI summary fallback)"

    ai_output = AiOutput(
        task_type="summarization",
        model_name=prompt_row.model_name if output_json else "none",
        prompt_version=prompt_row.prompt_version,
        input_ref_type="document",
        input_ref_id=document.id,
        output_json=output_json,
        output_text=output_json.get("plain_english_summary") if output_json else None,
        confidence=output_json.get("source_confidence") if output_json else "none",
        error_message=error,
    )
    db.add(ai_output)
    db.commit()
    return ai_output
