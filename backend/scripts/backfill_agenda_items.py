"""One-off backfill for the two things that only apply going forward otherwise:

1. Meeting.agenda_document_id / packet_document_id / minutes_document_id --
   the ingestion pipeline only started populating these in this change; existing
   meetings/documents predate it.
2. agenda_items rows for already-classified agenda documents -- the AI pipeline
   only runs agenda item extraction on documents it's about to classify for the
   first time, so documents classified before this change need a manual pass.

Safe to re-run: both steps only fill in what's missing.
"""

from app.ai.agenda_items import extract_agenda_items
from app.db import SessionLocal
from app.ingestion.pipeline import MEETING_DOCUMENT_FIELD_BY_TYPE
from app.models import Document, Meeting

BATCH_SIZE = 25


def backfill_meeting_links(db) -> int:
    linked = 0
    meetings = db.query(Meeting).all()
    for meeting in meetings:
        documents = (
            db.query(Document)
            .filter(
                Document.jurisdiction == meeting.jurisdiction,
                Document.body == meeting.body,
                Document.meeting_date == meeting.start_time.date(),
                Document.document_type.in_(MEETING_DOCUMENT_FIELD_BY_TYPE),
            )
            .all()
        )
        for document in documents:
            field = MEETING_DOCUMENT_FIELD_BY_TYPE[document.document_type]
            if getattr(meeting, field) is None:
                setattr(meeting, field, document.id)
                linked += 1
    db.commit()
    return linked


def backfill_agenda_items(db) -> int:
    agenda_docs = (
        db.query(Document)
        .filter(Document.document_type == "agenda", Document.parser_status == "parsed")
        .all()
    )
    count = 0
    for document in agenda_docs:
        extract_agenda_items(db, document)
        count += 1
        if count % BATCH_SIZE == 0:
            print(f"...{count}/{len(agenda_docs)}")
    return len(agenda_docs)


def main() -> None:
    db = SessionLocal()
    try:
        linked = backfill_meeting_links(db)
        print(f"Linked {linked} meeting/document reference(s).")
        total = backfill_agenda_items(db)
        print(f"Ran agenda item extraction over {total} agenda document(s).")
    finally:
        db.close()


if __name__ == "__main__":
    main()
