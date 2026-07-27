"""One-off: repoint the classification/agenda_item_extraction prompts at
qwen3:8b. llama3.1:8b's classification prompt set human_review_required=true
on 60-80% of documents (measured on real flagged docs, 2026-07-11); qwen3:8b
landed at 7% on the same sample with 100% valid structured output.

seed_prompts.py is intentionally idempotent (skips rows that already exist),
so it won't pick up a changed OLLAMA_TRIAGE_MODEL default for prompts already
seeded into this database -- this script updates those rows directly.

summarization/meeting_results_summary (OLLAMA_ANALYSIS_MODEL) are untouched:
qwen3:8b hasn't been evaluated against those prompts.

Safe to re-run.
"""

from app.db import SessionLocal
from app.models import Prompt

TRIAGE_TASK_TYPES = ("classification", "agenda_item_extraction")
NEW_MODEL = "qwen3:8b"


def main() -> None:
    db = SessionLocal()
    try:
        rows = (
            db.query(Prompt)
            .filter(Prompt.task_type.in_(TRIAGE_TASK_TYPES), Prompt.active.is_(True))
            .all()
        )
        for row in rows:
            print(f"{row.prompt_key} ({row.task_type}): {row.model_name} -> {NEW_MODEL}")
            row.model_name = NEW_MODEL
        db.commit()
        print(f"Updated {len(rows)} prompt row(s).")
    finally:
        db.close()


if __name__ == "__main__":
    main()
