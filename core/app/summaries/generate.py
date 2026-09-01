"""Generates a NarrativeSummary (daily or weekly): computes deterministic
stats (summaries/stats.py), narrates only the "Overview" section via the AI
layer (app/ai/ai_client.py, Ollama-primary/Claude-fallback) from those real
numbers, and stores both. Every number displayed anywhere (dashboard,
email) comes from stats_json, never from the model's own arithmetic --
see stats.py's docstring.

Scheduling is anchored to a fixed local wall-clock time (6am Pacific),
not a rolling "N hours since last run" window -- the latter is what
caused the real production bug this replaced: a 60s worker tick checking
"has ~24h passed" is vulnerable to generating twice in quick succession
whenever two ticks straddle a period boundary (confirmed live 2026-09-01:
two daily summaries generated 2m19s apart). Comparing "was a summary
already generated *today's Pacific calendar date*" is robust to that --
see period_already_exists.
"""

import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.ai import ai_client
from app.config import settings
from app.models import NarrativeSummary, Prompt
from app.summaries.stats import compute_stats, next_issue_number

logger = logging.getLogger(__name__)

PACIFIC = ZoneInfo("America/Los_Angeles")
SEND_HOUR_LOCAL = 6
WEEKLY_SEND_WEEKDAY = 0  # Monday

PERIOD_HOURS = {"daily": 24, "weekly": 24 * 7}


def is_due(period_type: str, now: datetime | None = None) -> bool:
    """True once it's past 6am Pacific on the day this period should send
    -- daily every day, weekly only on Mondays.
    """
    local = (now or datetime.now(timezone.utc)).astimezone(PACIFIC)
    if local.hour < SEND_HOUR_LOCAL:
        return False
    if period_type == "weekly":
        return local.weekday() == WEEKLY_SEND_WEEKDAY
    return True


def period_already_exists(db: Session, period_type: str, now: datetime | None = None) -> bool:
    """True if a summary of this period_type was already generated today
    (Pacific calendar date) -- compared by created_at (when it actually
    ran), not period_start, so this is robust regardless of exactly when
    within the day generation happened.
    """
    today_local = (now or datetime.now(timezone.utc)).astimezone(PACIFIC).date()
    existing = (
        db.query(NarrativeSummary)
        .filter(NarrativeSummary.period_type == period_type)
        .order_by(NarrativeSummary.created_at.desc())
        .first()
    )
    if existing is None:
        return False
    return existing.created_at.astimezone(PACIFIC).date() == today_local


def _period_bounds(period_type: str, now: datetime) -> tuple[datetime, datetime]:
    hours = PERIOD_HOURS[period_type]
    return now - timedelta(hours=hours), now


def _format_stats_summary(stats: dict) -> str:
    lines = [
        f"Documents filed: {stats['documents_filed']}",
        f"Meetings held: {len(stats['meetings_held'])}"
        + (
            " (" + "; ".join(f"{m['body']} on {m['date']}" for m in stats["meetings_held"][:10]) + ")"
            if stats["meetings_held"]
            else ""
        ),
        f"Meetings upcoming (next 14 days): {len(stats['meetings_upcoming'])}"
        + (
            " (" + "; ".join(f"{m['body']} on {m['date']}" for m in stats["meetings_upcoming"][:10]) + ")"
            if stats["meetings_upcoming"]
            else ""
        ),
        f"Alerts raised: {stats['alerts_raised']}"
        + (
            " (by level: " + ", ".join(f"L{lvl}={ct}" for lvl, ct in stats["alerts_by_level"].items()) + ")"
            if stats["alerts_by_level"]
            else ""
        ),
        f"Items awaiting human review: {stats['review_queue_count']}",
        f"New public notices: {len(stats['new_notices'])}",
    ]
    if stats["filing_by_agency"]:
        top = ", ".join(f"{row['agency']} ({row['count']})" for row in stats["filing_by_agency"][:5])
        lines.append(f"Top filing sources: {top}")
    return "\n".join(lines)


def generate_summary(db: Session, period_type: str, now: datetime | None = None) -> NarrativeSummary:
    now = now or datetime.now(timezone.utc)
    period_start, period_end = _period_bounds(period_type, now)

    stats = compute_stats(db, period_start, period_end)
    stats_summary = _format_stats_summary(stats)
    issue_number = next_issue_number(db, period_type)

    prompt_row = (
        db.query(Prompt)
        .filter(Prompt.prompt_key == "narrative_summary", Prompt.active.is_(True))
        .order_by(Prompt.created_at.desc())
        .first()
    )

    period_label = "daily" if period_type == "daily" else "weekly"
    title = f"{settings.project_name} — {period_label} recap, {period_end.date().isoformat()}"
    narrative_markdown = stats_summary
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
            stats_summary=stats_summary,
        )
        output_json, error = ai_client.generate_json(
            prompt_row.model_name, prompt, timeout=180.0, options=prompt_row.model_params
        )
        # Tolerate the model occasionally paraphrasing the field name to
        # "narrative" despite the prompt spelling out "narrative_markdown"
        # exactly -- confirmed live 2026-09-01, real qwen3:8b output used
        # "narrative" verbatim. Prefer the correct key; fall back rather
        # than discard an otherwise-good response over a naming slip.
        model_narrative = (output_json or {}).get("narrative_markdown") or (output_json or {}).get("narrative")
        if error or not output_json or not model_narrative:
            error_message = error or "model returned no narrative_markdown"
            logger.warning("narrative summary generation failed for %s period: %s", period_type, error_message)
        else:
            title = output_json.get("title") or title
            narrative_markdown = model_narrative
            model_name = prompt_row.model_name
            prompt_version = prompt_row.prompt_version

    stats["issue_number"] = issue_number

    summary = NarrativeSummary(
        period_type=period_type,
        period_start=period_start,
        period_end=period_end,
        title=title,
        narrative_markdown=narrative_markdown,
        stats_json=stats,
        model_name=model_name,
        prompt_version=prompt_version,
        error_message=error_message,
    )
    db.add(summary)
    try:
        db.commit()
    except IntegrityError:
        # Race: another process generated this exact period between our
        # period_already_exists check and this insert. Return the row it
        # created rather than erroring the whole batch.
        db.rollback()
        existing = (
            db.query(NarrativeSummary)
            .filter(NarrativeSummary.period_type == period_type, NarrativeSummary.period_start == period_start)
            .one()
        )
        return existing
    db.refresh(summary)
    return summary
