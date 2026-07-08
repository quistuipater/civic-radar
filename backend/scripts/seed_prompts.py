"""Seed versioned prompt templates into the `prompts` table (prd.md 10.3). Safe to re-run."""

from app.ai.prompts import PROMPT_DEFAULTS
from app.config import settings
from app.db import SessionLocal
from app.models import Prompt

MODEL_BY_TASK_TYPE = {
    "classification": settings.ollama_triage_model,
    "summarization": settings.ollama_analysis_model,
    "agenda_item_extraction": settings.ollama_triage_model,
    "meeting_results_summary": settings.ollama_analysis_model,
}


def main() -> None:
    db = SessionLocal()
    try:
        created = 0
        for row in PROMPT_DEFAULTS:
            row = dict(row)
            row["model_name"] = row["model_name"] or MODEL_BY_TASK_TYPE.get(row["task_type"], settings.ollama_triage_model)
            existing = (
                db.query(Prompt)
                .filter(Prompt.prompt_key == row["prompt_key"], Prompt.prompt_version == row["prompt_version"])
                .one_or_none()
            )
            if existing:
                continue
            db.add(Prompt(**row))
            created += 1
        db.commit()
        print(f"Seeded {created} new prompt(s).")
    finally:
        db.close()


if __name__ == "__main__":
    main()
