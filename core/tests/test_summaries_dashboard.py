from datetime import datetime, timezone

from app.models import NarrativeSummary


def _make_summary(db, **overrides):
    defaults = dict(
        period_type="daily",
        period_start=datetime(2026, 8, 31, tzinfo=timezone.utc),
        period_end=datetime(2026, 9, 1, tzinfo=timezone.utc),
        title="Ventura: quiet day",
        narrative_markdown="Nothing happened today.",
        stats_json={
            "documents_filed": 0,
            "meetings_held": [],
            "meetings_upcoming": [],
            "alerts_raised": 0,
            "alerts_by_level": {},
            "review_queue_count": 0,
            "filing_by_agency": [],
            "new_notices": [],
            "issue_number": 1,
        },
        model_name="qwen3:8b",
        prompt_version="v2",
    )
    defaults.update(overrides)
    summary = NarrativeSummary(**defaults)
    db.add(summary)
    db.flush()
    return summary


class TestSummariesListPage:
    def test_renders_with_no_summaries(self, db, client):
        resp = client.get("/summaries")
        assert resp.status_code == 200
        assert "No summaries generated yet" in resp.text

    def test_renders_a_summary(self, db, client):
        _make_summary(db)
        db.commit()

        resp = client.get("/summaries")
        assert resp.status_code == 200
        assert "Ventura: quiet day" in resp.text

    def test_filters_by_period_type(self, db, client):
        _make_summary(db, period_type="daily", title="Daily One")
        _make_summary(db, period_type="weekly", title="Weekly One")
        db.commit()

        resp = client.get("/summaries?period_type=weekly")
        assert resp.status_code == 200
        assert "Weekly One" in resp.text
        assert "Daily One" not in resp.text


class TestSummaryDetailPage:
    def test_renders_the_narrative_and_stats(self, db, client):
        summary = _make_summary(
            db,
            narrative_markdown="Some real content here.",
            stats_json={
                "documents_filed": 7,
                "meetings_held": [{"date": "2026-08-31", "body": "City Council", "meeting_type": None}],
                "meetings_upcoming": [],
                "alerts_raised": 2,
                "alerts_by_level": {"3": 2},
                "review_queue_count": 1,
                "filing_by_agency": [],
                "new_notices": [],
                "issue_number": 3,
            },
        )
        db.commit()

        resp = client.get(f"/summaries/{summary.id}")
        assert resp.status_code == 200
        assert "Some real content here" in resp.text
        assert ">7<" in resp.text
        assert "City Council" in resp.text

    def test_shows_error_note_when_generation_had_an_issue(self, db, client):
        summary = _make_summary(db, error_message="model returned invalid JSON")
        db.commit()

        resp = client.get(f"/summaries/{summary.id}")
        assert resp.status_code == 200
        assert "model returned invalid JSON" in resp.text

    def test_renders_not_found_for_unknown_id(self, db, client):
        resp = client.get("/summaries/00000000-0000-0000-0000-000000000000")
        assert resp.status_code == 200
        assert "not found" in resp.text.lower()
