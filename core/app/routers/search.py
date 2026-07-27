from fastapi import APIRouter, Depends
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.ai import ollama_client
from app.config import settings
from app.db import get_db
from app.models import Document, DocumentChunk, Issue

router = APIRouter(prefix="/api", tags=["search"])


@router.get("/search")
def search(q: str, limit: int = 50, db: Session = Depends(get_db)):
    """Keyword search across documents/issues plus semantic search over
    document_chunks (prd.md 9.14). The semantic pass embeds the query with the
    same Ollama model used at ingestion time and ranks chunks by cosine
    distance; it degrades to an empty list (rather than erroring) if Ollama is
    unreachable, matching the rest of the AI layer's reliability contract.
    """
    like = f"%{q}%"
    documents = (
        db.query(Document)
        .filter(
            or_(
                Document.title.ilike(like),
                Document.project_number.ilike(like),
                Document.ordinance_number.ilike(like),
                Document.resolution_number.ilike(like),
                Document.apn.ilike(like),
                Document.address.ilike(like),
            )
        )
        .limit(limit)
        .all()
    )
    issues = (
        db.query(Issue)
        .filter(or_(Issue.title.ilike(like), Issue.summary.ilike(like)))
        .limit(limit)
        .all()
    )

    semantic_matches = []
    query_embedding, error = ollama_client.embed(settings.ollama_embedding_model, q)
    if query_embedding is not None:
        distance = DocumentChunk.embedding.cosine_distance(query_embedding).label("distance")
        rows = (
            db.query(DocumentChunk, Document, distance)
            .join(Document, Document.id == DocumentChunk.document_id)
            .filter(DocumentChunk.embedding.isnot(None))
            .order_by(distance)
            .limit(limit)
            .all()
        )
        semantic_matches = [
            {
                "document_id": doc.id,
                "document_title": doc.title,
                "chunk_id": chunk.id,
                "page_start": chunk.page_start,
                "page_end": chunk.page_end,
                "snippet": chunk.text[:400],
                "distance": float(dist),
            }
            for chunk, doc, dist in rows
        ]

    return {
        "documents": [{"id": d.id, "title": d.title, "document_type": d.document_type} for d in documents],
        "issues": [{"id": i.id, "title": i.title, "slug": i.slug, "status": i.status} for i in issues],
        "semantic_matches": semantic_matches,
    }
