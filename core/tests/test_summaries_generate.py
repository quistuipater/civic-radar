"""Tests for app.summaries.generate -- computes deterministic stats
(stats.py), narrates only the Overview via ai_client (mocked here,
matching test_classify.py's pattern), and records a NarrativeSummary row
either way (degrade-gracefully, not raise, on a missing prompt or a
failed model call). Scheduling (is_due/period_already_exists) is anchored
to 6am Pacific -- see generate.py's module docstring for why a rolling
"N hours since last run" window caused a real production bug.
"""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import app.summaries.generate as generate_module
from app.summaries.generate import generate_summary, is_due, period_already_exists
from tests.conftest import make_prompt

PACIFIC = ZoneInfo("America/Los_Angeles")


class TestGenerateSummary:
    def test_uses_model_output_when_prompt_configured(self, db, monkeypatch):
        make_prompt(
            db,
            prompt_key="narrative_summary",
            prompt_version="v2",
            prompt_text="{project_name} {jurisdiction} {period_label} {period_start} {period_end} {stats_summary}",
        )
        monkeypatch.setattr(
            generate_module.ai_client,
            "generate_json",
            lambda *a, **k: ({"title": "Quiet week", "narrative_markdown": "Nothing happened."}, None),
        )

        summary = generate_summary(db, "daily")

        assert summary.period_type == "daily"
        assert summary.title == "Quiet week"
        assert summary.narrative_markdown == "Nothing happened."
        assert summary.error_message is None
        assert summary.stats_json["documents_filed"] == 0
        assert summary.stats_json["issue_number"] == 1

    def test_falls_back_to_stats_summary_when_no_prompt_configured(self, db):
        summary = generate_summary(db, "daily")

        assert summary.error_message == "no active narrative_summary prompt configured"
        assert "Documents filed" in summary.narrative_markdown
        assert summary.model_name == "none"

    def test_tolerates_the_model_using_narrative_instead_of_narrative_markdown(self, db, monkeypatch):
        make_prompt(db, prompt_key="narrative_summary", prompt_text="{stats_summary}")
        monkeypatch.setattr(
            generate_module.ai_client,
            "generate_json",
            lambda *a, **k: ({"title": "Quiet week", "narrative": "Nothing happened (wrong key)."}, None),
        )

        summary = generate_summary(db, "daily")

        assert summary.narrative_markdown == "Nothing happened (wrong key)."
        assert summary.error_message is None

    def test_falls_back_when_model_call_fails(self, db, monkeypatch):
        make_prompt(db, prompt_key="narrative_summary", prompt_text="{stats_summary}")
        monkeypatch.setattr(
            generate_module.ai_client, "generate_json", lambda *a, **k: (None, "model returned invalid JSON")
        )

        summary = generate_summary(db, "daily")

        assert summary.error_message == "model returned invalid JSON"
        assert "Documents filed" in summary.narrative_markdown

    def test_weekly_period_spans_seven_days(self, db):
        now = datetime(2026, 9, 1, tzinfo=timezone.utc)
        summary = generate_summary(db, "weekly", now=now)

        assert (summary.period_end - summary.period_start).days == 7

    def test_issue_number_increments_per_period_type(self, db):
        first = generate_summary(db, "daily")
        second = generate_summary(db, "daily", now=datetime.now(timezone.utc))
        weekly = generate_summary(db, "weekly")

        assert first.stats_json["issue_number"] == 1
        assert second.stats_json["issue_number"] == 2
        assert weekly.stats_json["issue_number"] == 1

    def test_a_race_on_the_same_period_returns_the_existing_row_instead_of_crashing(self, db):
        now = datetime(2026, 9, 1, 6, 30, tzinfo=timezone.utc)
        first = generate_summary(db, "daily", now=now)

        # Same exact instant -> identical period_start -> would violate the
        # unique constraint if not handled.
        second = generate_summary(db, "daily", now=now)

        assert second.id == first.id


class TestIsDue:
    def test_daily_is_due_after_6am_pacific(self):
        morning = datetime(2026, 9, 1, 6, 0, tzinfo=PACIFIC).astimezone(timezone.utc)
        assert is_due("daily", now=morning) is True

    def test_daily_is_not_due_before_6am_pacific(self):
        early = datetime(2026, 9, 1, 5, 59, tzinfo=PACIFIC).astimezone(timezone.utc)
        assert is_due("daily", now=early) is False

    def test_weekly_is_due_only_on_monday(self):
        # 2026-09-07 is a Monday
        monday = datetime(2026, 9, 7, 7, 0, tzinfo=PACIFIC).astimezone(timezone.utc)
        tuesday = datetime(2026, 9, 8, 7, 0, tzinfo=PACIFIC).astimezone(timezone.utc)
        assert is_due("weekly", now=monday) is True
        assert is_due("weekly", now=tuesday) is False


class TestPeriodAlreadyExists:
    def test_false_when_no_summaries_exist(self, db):
        assert period_already_exists(db, "daily") is False

    def test_true_immediately_after_generating(self, db):
        now = datetime(2026, 9, 1, 14, 0, tzinfo=timezone.utc)  # 7am Pacific
        generate_summary(db, "daily", now=now)

        assert period_already_exists(db, "daily", now=now + generate_module.timedelta(minutes=2)) is True

    def test_false_the_next_pacific_calendar_day(self, db):
        now = datetime(2026, 9, 1, 14, 0, tzinfo=timezone.utc)
        generate_summary(db, "daily", now=now)

        next_day = now + generate_module.timedelta(days=1)
        assert period_already_exists(db, "daily", now=next_day) is False

    def test_daily_and_weekly_are_tracked_independently(self, db):
        now = datetime(2026, 9, 1, 14, 0, tzinfo=timezone.utc)
        generate_summary(db, "daily", now=now)

        assert period_already_exists(db, "weekly", now=now) is False
