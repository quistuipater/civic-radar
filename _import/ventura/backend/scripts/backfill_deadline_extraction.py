"""One-off backfill: public_hearing_date/comment_deadline extraction was
added to extract_structured_fields() after every existing document had
already been parsed, so parse_document() never re-runs for them (it
early-exits when parser_status == "parsed"). Re-applies just the regex
extraction against each document's already-extracted text -- no re-parsing
or OCR needed, just the cheap regex pass.

Safe to re-run: only fills fields that are currently None, per the same
"don't overwrite an existing value" rule parse_document() itself follows.
"""

from app.db import SessionLocal
from app.models import Document
from app.parsing.extract import extract_structured_fields

BATCH_SIZE = 100


def main() -> None:
    db = SessionLocal()
    try:
        documents = (
            db.query(Document)
            .filter(
                Document.parser_status == "parsed",
                Document.extracted_text_path.isnot(None),
                Document.public_hearing_date.is_(None) | Document.comment_deadline.is_(None),
            )
            .all()
        )
        print(f"{len(documents)} document(s) to check")

        updated = 0
        for document in documents:
            try:
                with open(document.extracted_text_path, encoding="utf-8", errors="ignore") as f:
                    text = f.read()
            except OSError as exc:
                print(f"  skip {document.id}: cannot read {document.extracted_text_path}: {exc}")
                continue

            fields = extract_structured_fields(text)
            changed = False
            for key in ("public_hearing_date", "comment_deadline"):
                if key in fields and getattr(document, key) is None:
                    setattr(document, key, fields[key])
                    changed = True
            if changed:
                updated += 1
                if updated % BATCH_SIZE == 0:
                    db.commit()
                    print(f"  ...{updated} updated so far")

        db.commit()
        print(f"done: {updated} document(s) updated")
    finally:
        db.close()


if __name__ == "__main__":
    main()
