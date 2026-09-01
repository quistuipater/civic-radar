from datetime import datetime, timezone

from app.models import NarrativeSummary
from app.summaries.render import render_summary_email


def _make_summary(**overrides) -> NarrativeSummary:
    defaults = dict(
        period_type="daily",
        period_start=datetime(2026, 8, 31, tzinfo=timezone.utc),
        period_end=datetime(2026, 9, 1, tzinfo=timezone.utc),
        title="Ventura: quiet day",
        narrative_markdown="Nothing happened today.",
        stats_json={
            "documents_filed": 3,
            "meetings_held": [],
            "meetings_upcoming": [{"date": "2026-09-05", "body": "City Council", "meeting_type": None}],
            "alerts_raised": 0,
            "alerts_by_level": {},
            "review_queue_count": 1,
            "filing_by_agency": [],
            "new_notices": [{"title": "A Notice", "url": "/documents/x"}],
            "issue_number": 5,
        },
        model_name="qwen3:8b",
        prompt_version="v2",
        created_at=datetime(2026, 9, 1, 14, 0, tzinfo=timezone.utc),
    )
    defaults.update(overrides)
    return NarrativeSummary(**defaults)


class TestRenderSummaryEmail:
    def test_subject_is_the_title(self):
        subject, _, _ = render_summary_email(_make_summary())
        assert subject == "Ventura: quiet day"

    def test_html_body_includes_narrative_and_stats(self):
        _, _, html_body = render_summary_email(_make_summary())
        assert "Nothing happened today" in html_body
        assert "A Notice" in html_body
        assert "City Council" in html_body
        assert ">3<" in html_body  # documents_filed stat

    def test_html_body_uses_light_theme_for_email(self):
        _, _, html_body = render_summary_email(_make_summary())
        assert "#eaeee7" in html_body  # light --paper value
        assert "#131a17" not in html_body  # dark --paper value must not appear

    def test_html_body_has_no_unresolved_css_variables(self):
        # CSS custom properties (var(--x)) render fine in a browser -- which
        # is why the dashboard page looks right -- but email clients
        # (Gmail especially) have poor/inconsistent support for them,
        # silently dropping the styling. Every var(--x) use must be
        # resolved to a literal value before the email is sent.
        _, _, html_body = render_summary_email(_make_summary())
        assert "var(--" not in html_body

    def test_html_body_inlines_styles_as_attributes(self):
        # <style> block support (regardless of placement or whether
        # variables are resolved) is itself unreliable across email
        # clients -- confirmed live 2026-09-01 against real Gmail
        # rendering. Every element's computed style must be present as an
        # inline style="" attribute, which every mainstream client honors.
        _, _, html_body = render_summary_email(_make_summary())
        assert 'class="masthead"' in html_body
        assert "border-collapse:collapse" in html_body
        assert "margin:1.1rem 0 0.3rem" in html_body
        assert "background:#eaeee7" in html_body  # light --paper, inlined on .civic-report

    def test_plain_text_body_includes_narrative_and_stats(self):
        _, plain_text, _ = render_summary_email(_make_summary())
        assert "Nothing happened today" in plain_text
        assert "Docs filed: 3" in plain_text
        assert "A Notice" in plain_text

    def test_html_body_escapes_content(self):
        summary = _make_summary(narrative_markdown="<script>alert(1)</script>")
        _, _, html_body = render_summary_email(summary)
        assert "<script>alert" not in html_body

    def test_error_message_surfaces_a_note(self):
        summary = _make_summary(error_message="model returned invalid JSON")
        _, plain_text, html_body = render_summary_email(summary)
        assert "model returned invalid JSON" in plain_text
        assert "model returned invalid JSON" in html_body
