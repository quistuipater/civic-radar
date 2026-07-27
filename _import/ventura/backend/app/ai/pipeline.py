import logging

from sqlalchemy.orm import Session

from app.ai.agenda_items import extract_agenda_items
from app.ai.classify import classify_document
from app.ai.embed import embed_document_chunks
from app.ai.meeting_results import extract_meeting_results
from app.ai.summarize import summarize_document
from app.models import AiOutput, Document

logger = logging.getLogger(__name__)

# Only run the (relatively expensive) AI layer on document types that actually
# carry substantive content — skip raw page snapshots (prd.md 20.3 resource constraints).
CLASSIFIABLE_TYPES = {"agenda", "minutes", "packet", "notice", "pdf"}


def run_ai_pipeline(db: Session, document: Document) -> None:
    if document.document_type not in CLASSIFIABLE_TYPES:
        return
    if document.parser_status != "parsed":
        return

    embed_document_chunks(db, document)
    extract_agenda_items(db, document)
    extract_meeting_results(db, document)

    already_classified = (
        db.query(AiOutput)
        .filter(
            AiOutput.input_ref_type == "document",
            AiOutput.input_ref_id == document.id,
            AiOutput.task_type == "classification",
        )
        .first()
    )
    if already_classified:
        return

    classify_document(db, document)
    summarize_document(db, document)
