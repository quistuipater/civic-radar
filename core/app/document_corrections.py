"""Shared logic for applying a human correction to a Document -- used by both
the REST API (routers/documents.py's PATCH) and the dashboard's edit form
(dashboard.py), so the two don't drift on what "correcting a document" means.
See routers/documents.py's update_document docstring for why corrected_text
is more than a plain column assignment.
"""

from pathlib import Path

from sqlalchemy.orm import Session

from app.models import Document, DocumentChunk
from app.parsing.extract import ParsedDocument, ParsedPage, chunk_pages, extract_structured_fields


def apply_document_corrections(db: Session, document: Document, updates: dict, corrected_text: str | None) -> None:
    for key, value in updates.items():
        setattr(document, key, value)

    if corrected_text is not None:
        text_path = (
            Path(document.extracted_text_path)
            if document.extracted_text_path
            else Path(document.archive_path).with_suffix(Path(document.archive_path).suffix + ".txt")
        )
        text_path.write_text(corrected_text)
        document.extracted_text_path = str(text_path)

        db.query(DocumentChunk).filter(DocumentChunk.document_id == document.id).delete()
        parsed = ParsedDocument(full_text=corrected_text, pages=[ParsedPage(1, corrected_text)])
        for chunk in chunk_pages(parsed):
            db.add(DocumentChunk(document_id=document.id, **chunk))

        for key, value in extract_structured_fields(corrected_text).items():
            if getattr(document, key, None) is None:
                setattr(document, key, value)

        document.parser_status = "parsed"
        document.parser_error = None

        # Supplying corrected_text *is* the human review -- clear the flag
        # unless the caller explicitly set needs_human_review itself above.
        if "needs_human_review" not in updates:
            document.needs_human_review = False

    db.commit()
