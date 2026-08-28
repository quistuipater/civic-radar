import logging

from sqlalchemy.orm import Session

from app.ai import ollama_client
from app.ai.heuristics import heuristic_classification
from app.ai.prompts import TOPIC_TAXONOMY
from app.config import settings
from app.models import AiOutput, Document, Prompt

logger = logging.getLogger(__name__)

MAX_CHARS = 8000


def classify_document(db: Session, document: Document) -> AiOutput:
    prompt_row = (
        db.query(Prompt)
        .filter(Prompt.prompt_key == "agenda_item_classification", Prompt.active.is_(True))
        .order_by(Prompt.created_at.desc())
        .first()
    )

    text = load_document_text(document)
    output_json: dict | None = None
    error: str | None = None
    model_name = prompt_row.model_name if prompt_row else "heuristic"
    prompt_version = prompt_row.prompt_version if prompt_row else "heuristic"

    if prompt_row and ollama_client.is_available():
        prompt = prompt_row.prompt_text.format(
            project_name=settings.project_name,
            taxonomy=", ".join(TOPIC_TAXONOMY),
            title=document.title or "",
            jurisdiction=document.jurisdiction or "",
            agency=document.agency or "",
            meeting_date=document.meeting_date or "",
            text=text[:MAX_CHARS],
        )
        output_json, error = ollama_client.generate_json(prompt_row.model_name, prompt, options=prompt_row.model_params)

    if output_json is None:
        output_json = heuristic_classification(document.title, text, document.meeting_date)
        model_name = "heuristic"
        prompt_version = "heuristic-v1"
        if error:
            logger.info("falling back to heuristic classification for document %s: %s", document.id, error)

    ai_output = AiOutput(
        task_type="classification",
        model_name=model_name,
        prompt_version=prompt_version,
        input_ref_type="document",
        input_ref_id=document.id,
        output_json=output_json,
        confidence=output_json.get("confidence"),
        error_message=error,
    )
    db.add(ai_output)
    db.commit()
    return ai_output


def load_document_text(document: Document) -> str:
    if document.extracted_text_path:
        try:
            with open(document.extracted_text_path, encoding="utf-8", errors="ignore") as f:
                return f.read()
        except OSError:
            pass
    return document.title or ""
