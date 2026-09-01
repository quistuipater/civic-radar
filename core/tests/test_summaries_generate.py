"""Tests for app.summaries.generate -- builds the digest rollup, narrates it
via ai_client (mocked here, matching test_classify.py's pattern), and
records a NarrativeSummary row either way (degrade-gracefully, not raise,
on a missing prompt or a failed model call).
"""

from datetime import datetime, timezone

import app.summaries.generate as generate_module
from app.models import NarrativeSummary
from app.summaries.generate import generate_summary, period_already_exists
from tests.conftest import make_prompt


class TestGenerateSummary:
    def test_uses_model_output_when_prompt_configured(self, db, monkeypatch):
        make_prompt(
            db,
            prompt_key="narrative_summary",
            prompt_version="v1",
            prompt_text="{project_name} {jurisdiction} {period_label} {period_start} {period_end} {digest_markdown}",
        )
        monkeypatch.setattr(
            generate_module.ai_client,
            "generate_json",
            lambda *a, **k: ({"title": "Quiet week", "narrative_markdown": "## Nothing happened"}, None),
        )

        summary = generate_summary(db, "daily")

        assert summary.period_type == "daily"
        assert summary.title == "Quiet week"
        assert summary.narrative_markdown == "## Nothing happened"
        assert summary.error_message is None
        assert summary.id is not None

    def test_falls_back_to_raw_digest_when_no_prompt_configured(self, db):
        summary = generate_summary(db, "daily")

        assert summary.error_message == "no active narrative_summary prompt configured"
        assert "Daily Digest" in summary.narrative_markdown
        assert summary.model_name == "none"

    def test_falls_back_to_raw_digest_when_model_call_fails(self, db, monkeypatch):
        make_prompt(db, prompt_key="narrative_summary", prompt_text="{digest_markdown}")
        monkeypatch.setattr(
            generate_module.ai_client, "generate_json", lambda *a, **k: (None, "model returned invalid JSON")
        )

        summary = generate_summary(db, "daily")

        assert summary.error_message == "model returned invalid JSON"
        assert "Daily Digest" in summary.narrative_markdown

    def test_weekly_period_spans_seven_days(self, db):
        now = datetime(2026, 9, 1, tzinfo=timezone.utc)
        summary = generate_summary(db, "weekly", now=now)

        assert (summary.period_end - summary.period_start).days == 7

    def test_second_call_for_same_period_does_not_crash_on_unique_constraint(self, db):
        now = datetime(2026, 9, 1, tzinfo=timezone.utc)
        generate_summary(db, "daily", now=now)

        # A near-identical timestamp a few seconds later still lands on the
        # same calendar period -- generate_summary itself doesn't dedupe
        # (period_already_exists is the caller's job, see worker.py), but a
        # second insert with a different period_start must not violate the
        # unique constraint since the timestamps differ at all.
        second = generate_summary(db, "daily", now=now + generate_module.timedelta(seconds=1))
        assert second.id is not None


class TestPeriodAlreadyExists:
    def test_false_when_no_summaries_exist(self, db):
        assert period_already_exists(db, "daily") is False

    def test_true_immediately_after_generating(self, db):
        now = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
        generate_summary(db, "daily", now=now)

        assert period_already_exists(db, "daily", now=now + generate_module.timedelta(minutes=1)) is True

    def test_false_once_a_full_day_has_passed_for_daily(self, db):
        now = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
        generate_summary(db, "daily", now=now)

        later = now + generate_module.timedelta(days=1, hours=1)
        assert period_already_exists(db, "daily", now=later) is False

    def test_daily_and_weekly_are_tracked_independently(self, db):
        now = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
        generate_summary(db, "daily", now=now)

        assert period_already_exists(db, "weekly", now=now) is False
