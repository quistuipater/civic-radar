from datetime import datetime, timezone

from app.models import NarrativeSummary
from app.summaries.render import render_summary_email


def _make_summary(**overrides) -> NarrativeSummary:
    defaults = dict(
        period_type="daily",
        period_start=datetime(2026, 8, 31, tzinfo=timezone.utc),
        period_end=datetime(2026, 9, 1, tzinfo=timezone.utc),
        title="Ventura: quiet day",
        narrative_markdown="## Nothing happened\n\nNo new notices today.",
        model_name="qwen3:8b",
        prompt_version="v1",
    )
    defaults.update(overrides)
    return NarrativeSummary(**defaults)


class TestRenderSummaryEmail:
    def test_subject_is_the_title(self):
        subject, _, _ = render_summary_email(_make_summary())
        assert subject == "Ventura: quiet day"

    def test_markdown_body_includes_narrative_and_period(self):
        _, markdown_body, _ = render_summary_email(_make_summary())
        assert "Nothing happened" in markdown_body
        assert "2026-08-31" in markdown_body
        assert "2026-09-01" in markdown_body

    def test_html_body_escapes_content(self):
        summary = _make_summary(narrative_markdown="<script>alert(1)</script>")
        _, _, html_body = render_summary_email(summary)
        assert "<script>" not in html_body
        assert "&lt;script&gt;" in html_body

    def test_error_message_surfaces_a_note_in_the_footer(self):
        summary = _make_summary(error_message="model returned invalid JSON")
        _, markdown_body, _ = render_summary_email(summary)
        assert "model returned invalid JSON" in markdown_body
