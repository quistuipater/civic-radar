"""One-off backfill: embed any document_chunks left over from before embeddings
were wired into the ingestion pipeline. New chunks get embedded automatically
via app.ai.pipeline going forward; this just covers the existing backlog. Safe
to re-run — only chunks with embedding IS NULL are touched.
"""

from app.ai.embed import embed_document_chunks
from app.db import SessionLocal
from app.models import Document, DocumentChunk

BATCH_SIZE = 25


def main() -> None:
    db = SessionLocal()
    try:
        document_ids = (
            db.query(DocumentChunk.document_id)
            .filter(DocumentChunk.embedding.is_(None))
            .distinct()
            .all()
        )
        print(f"{len(document_ids)} document(s) with unembedded chunks.")
        for i, (document_id,) in enumerate(document_ids, start=1):
            document = db.get(Document, document_id)
            if document is None:
                continue
            embed_document_chunks(db, document)
            if i % BATCH_SIZE == 0:
                print(f"...{i}/{len(document_ids)}")
        print("Done.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
