"""One-off backfill: extract_meeting_results() only runs from run_ai_pipeline,
which the worker only calls for documents that don't yet have a
classification AiOutput -- meaning already-classified minutes documents
(the vast majority, since backfill_ai_reclassify.py already ran once) will
never get meeting-results extraction from the normal worker cycle. Runs it
directly against every parsed minutes document instead.

Safe to re-run: extract_meeting_results() itself is idempotent (returns the
existing AiOutput if one's already there for that document).
"""

from app.ai.meeting_results import extract_meeting_results
from app.db import SessionLocal
from app.models import Document

BATCH_SIZE = 25


def main() -> None:
    db = SessionLocal()
    try:
        minutes_docs = (
            db.query(Document)
            .filter(Document.document_type == "minutes", Document.parser_status == "parsed")
            .all()
        )
        print(f"{len(minutes_docs)} minutes document(s) to check")

        extracted = 0
        for i, document in enumerate(minutes_docs, start=1):
            result = extract_meeting_results(db, document)
            if result is not None and result.output_json is not None:
                extracted += 1
            if i % BATCH_SIZE == 0:
                print(f"  ...{i}/{len(minutes_docs)}")

        print(f"done: {extracted} document(s) got a real (non-error) meeting-results summary")
    finally:
        db.close()


if __name__ == "__main__":
    main()
