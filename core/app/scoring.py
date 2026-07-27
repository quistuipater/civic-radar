"""Alert-level computation from a document's classification output (prd.md 9.12, 12)."""

from datetime import date, datetime, timezone


def alert_level_for(
    importance_score: int,
    urgency_score: int,
    transparency_risk_score: int,
    meeting_date: date | None,
) -> int:
    """Levels: 1 Captured, 2 Relevant, 3 Action Window, 4 High Impact/Imminent."""
    days_out = None
    if meeting_date:
        days_out = (meeting_date - datetime.now(timezone.utc).date()).days

    high_impact = importance_score >= 8 or transparency_risk_score >= 8
    imminent = days_out is not None and 0 <= days_out <= 7
    action_window = imminent or urgency_score >= 6

    if high_impact and (imminent or urgency_score >= 8):
        return 4
    if action_window:
        return 3
    if importance_score >= 3 or transparency_risk_score >= 3:
        return 2
    return 1
