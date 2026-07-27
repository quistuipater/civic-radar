import logging

from sqlalchemy.orm import Session

from app.ai import ollama_client
from app.config import settings
from app.models import Document, DocumentChunk

logger = logging.getLogger(__name__)

MAX_CHARS = 8000


def embed_document_chunks(db: Session, document: Document) -> None:
    """Populate embeddings for any of this document's chunks that don't have one
    yet. Safe to call repeatedly — already-embedded chunks are skipped. Degrades
    silently (leaves embedding NULL) if Ollama is unreachable, consistent with
    the rest of the AI layer never blocking the pipeline (prd.md 21).
    """
    if not ollama_client.is_available():
        return

    chunks = (
        db.query(DocumentChunk)
        .filter(DocumentChunk.document_id == document.id, DocumentChunk.embedding.is_(None))
        .all()
    )
    for chunk in chunks:
        vector, error = ollama_client.embed(settings.ollama_embedding_model, chunk.text[:MAX_CHARS])
        if vector is None:
            logger.info("skipping embedding for chunk %s: %s", chunk.id, error)
            continue
        chunk.embedding = vector
    db.commit()
