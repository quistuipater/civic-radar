"""Generates a NarrativeSummary (daily or weekly): builds the same
structured rollup export.digest.py already computes for the in-app Daily
Digest (no separate data-gathering layer -- see that module's docstring
for why it's a pure rollup over already-classified data, no new AI calls
at that layer), then narrates it via the AI layer (app/ai/ai_client.py,
Ollama-primary/Claude-fallback) into a short markdown recap.

Mirrors the degrade-gracefully pattern used everywhere else in the AI
layer: a missing prompt row or unavailable Ollama produces a
NarrativeSummary row with error_message set and a minimal fallback
narrative, rather than raising and silently skipping the period (an
operator should be able to see "this period's summary failed" in the
dashboard, not just an absence).
"""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.ai import ai_client
from app.config import settings
from app.export.digest import build_daily_digest, render_digest_markdown
from app.models import NarrativeSummary, Prompt

logger = logging.getLogger(__name__)

PERIOD_HOURS = {"daily": 24, "weekly": 24 * 7}


def _period_bounds(period_type: str, now: datetime) -> tuple[datetime, datetime]:
    hours = PERIOD_HOURS[period_type]
    return now - timedelta(hours=hours), now


def generate_summary(db: Session, period_type: str, now: datetime | None = None) -> NarrativeSummary:
    """Idempotent per (period_type, period_start) via the unique constraint
    on NarrativeSummary -- callers (worker.py's scheduling) are expected to
    check existence first via period_already_exists() rather than rely on
    this to no-op, but this still won't create a duplicate row if called
    twice for the same period.
    """
    now = now or datetime.now(timezone.utc)
    period_start, period_end = _period_bounds(period_type, now)

    digest = build_daily_digest(db, window_hours=PERIOD_HOURS[period_type])
    digest_markdown = render_digest_markdown(digest)

    prompt_row = (
        db.query(Prompt)
        .filter(Prompt.prompt_key == "narrative_summary", Prompt.active.is_(True))
        .order_by(Prompt.created_at.desc())
        .first()
    )

    period_label = "daily" if period_type == "daily" else "weekly"
    title = f"{settings.project_name} — {period_label} recap, {period_end.date().isoformat()}"
    narrative_markdown = digest_markdown
    model_name = "none"
    prompt_version = "none"
    error_message: str | None = None

    if prompt_row is None:
        error_message = "no active narrative_summary prompt configured"
    else:
        prompt = prompt_row.prompt_text.format(
            project_name=settings.project_name,
            jurisdiction=settings.project_name,
            period_label=period_label,
            period_start=period_start.date().isoformat(),
            period_end=period_end.date().isoformat(),
            digest_markdown=digest_markdown,
        )
        output_json, error = ai_client.generate_json(
            prompt_row.model_name, prompt, timeout=180.0, options=prompt_row.model_params
        )
        if error or not output_json or not output_json.get("narrative_markdown"):
            error_message = error or "model returned no narrative_markdown"
            logger.warning("narrative summary generation failed for %s period: %s", period_type, error_message)
        else:
            title = output_json.get("title") or title
            narrative_markdown = output_json["narrative_markdown"]
            model_name = prompt_row.model_name
            prompt_version = prompt_row.prompt_version

    summary = NarrativeSummary(
        period_type=period_type,
        period_start=period_start,
        period_end=period_end,
        title=title,
        narrative_markdown=narrative_markdown,
        model_name=model_name,
        prompt_version=prompt_version,
        error_message=error_message,
    )
    db.add(summary)
    db.commit()
    db.refresh(summary)
    return summary


def period_already_exists(db: Session, period_type: str, now: datetime | None = None) -> bool:
    now = now or datetime.now(timezone.utc)
    period_start, _ = _period_bounds(period_type, now)
    # Two runs on the same calendar day/week would compute slightly
    # different period_start timestamps (sub-second drift), so compare by
    # date rather than an exact timestamp match.
    existing = (
        db.query(NarrativeSummary)
        .filter(NarrativeSummary.period_type == period_type)
        .order_by(NarrativeSummary.period_start.desc())
        .first()
    )
    if existing is None:
        return False
    return existing.period_start.date() == period_start.date()
