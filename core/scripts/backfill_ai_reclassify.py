"""One-off backfill: gpt-oss:20b was producing garbled output on madhatter
(MXFP4/kernel issue, see README), so essentially every classification fell
back to the heuristic path and every summarization failed outright, well
before this was caught. Now that OLLAMA_TRIAGE_MODEL/OLLAMA_ANALYSIS_MODEL
are pinned to a model confirmed to work (llama3.1:8b), re-run both over every
already-parsed document that doesn't yet have a real AI output.

Safe to re-run: skips any document whose latest classification/summary
already came from a real model (not "heuristic"/"none").
"""

from app.ai.classify import classify_document
from app.ai.pipeline import CLASSIFIABLE_TYPES
from app.ai.summarize import summarize_document
from app.db import SessionLocal
from app.models import AiOutput, Document

BATCH_SIZE = 25


def _latest_model(db, document_id, task_type) -> str | None:
    row = (
        db.query(AiOutput)
        .filter(
            AiOutput.input_ref_type == "document",
            AiOutput.input_ref_id == document_id,
            AiOutput.task_type == task_type,
        )
        .order_by(AiOutput.created_at.desc())
        .first()
    )
    return row.model_name if row else None


def main() -> None:
    db = SessionLocal()
    try:
        documents = (
            db.query(Document)
            .filter(Document.document_type.in_(CLASSIFIABLE_TYPES), Document.parser_status == "parsed")
            .all()
        )
        print(f"{len(documents)} parsed document(s) in scope.")
        reclassified = resummarized = 0
        for i, document in enumerate(documents, start=1):
            if _latest_model(db, document.id, "classification") in (None, "heuristic"):
                classify_document(db, document)
                reclassified += 1
            if _latest_model(db, document.id, "summarization") in (None, "none"):
                summarize_document(db, document)
                resummarized += 1
            if i % BATCH_SIZE == 0:
                print(f"...{i}/{len(documents)} (reclassified={reclassified}, resummarized={resummarized})")
        print(f"Done. reclassified={reclassified}, resummarized={resummarized}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
