"""Formats a NarrativeSummary for email -- renders the same summary_report.html
template the dashboard uses (light theme, standalone <html> document) via a
plain jinja2.Environment rather than FastAPI's templates object, so there's
one source of truth for the report layout instead of a second HTML-building
implementation living here.
"""

import jinja2
from markupsafe import escape

from app.config import settings
from app.models import NarrativeSummary

_env = jinja2.Environment(loader=jinja2.FileSystemLoader("app/templates"), autoescape=True)


def render_summary_email(summary: NarrativeSummary) -> tuple[str, str, str]:
    """Returns (subject, plain_text_body, html_body)."""
    subject = summary.title
    stats = summary.stats_json or {}

    report_fragment = _env.get_template("summary_report.html").render(
        summary=summary, stats=stats, project_name=settings.project_name, theme="light"
    )
    html_body = (
        "<!doctype html><html><head><meta charset=\"utf-8\">"
        f"<title>{escape(subject)}</title></head>"
        f"<body style=\"margin:0;\">{report_fragment}</body></html>"
    )

    plain_text_body = _render_plain_text(summary, stats)
    return subject, plain_text_body, html_body


def _render_plain_text(summary: NarrativeSummary, stats: dict) -> str:
    lines = [
        summary.title,
        f"{summary.period_type} recap — {summary.period_start.date()} to {summary.period_end.date()}",
        "",
        summary.narrative_markdown,
        "",
        f"Docs filed: {stats.get('documents_filed', 0)} | "
        f"Meetings held: {len(stats.get('meetings_held', []))} | "
        f"Alerts raised: {stats.get('alerts_raised', 0)} | "
        f"Awaiting review: {stats.get('review_queue_count', 0)}",
    ]
    if stats.get("meetings_upcoming"):
        lines.append("")
        lines.append("On the docket:")
        for m in stats["meetings_upcoming"]:
            lines.append(f"  - {m['date']}: {m['body']}")
    if stats.get("new_notices"):
        lines.append("")
        lines.append("New public notices:")
        for n in stats["new_notices"]:
            lines.append(f"  - {n['title']}")
    if summary.error_message:
        lines.append("")
        lines.append(f"Note: overview narration had an issue ({summary.error_message}); stats above are still real.")
    lines.append("")
    lines.append(f"— {settings.project_name}, internal draft, not for public distribution.")
    return "\n".join(lines)
