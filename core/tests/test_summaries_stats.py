"""Tests for app.summaries.stats -- every number here should be a direct
query result over a known window, verified against hand-built fixtures
(not just "doesn't crash") since these are the numbers generate.py hands
the model as facts it's not allowed to recompute.
"""

from datetime import datetime, timedelta, timezone

from app.summaries.stats import compute_stats, next_issue_number
from tests.conftest import make_alert, make_document, make_meeting

NOW = datetime(2026, 9, 1, 14, 0, tzinfo=timezone.utc)
PERIOD_START = NOW - timedelta(hours=24)


class TestComputeStats:
    def test_counts_documents_filed_within_the_window_only(self, db):
        make_document(db, created_at=NOW - timedelta(hours=1))
        make_document(db, created_at=NOW - timedelta(hours=2))
        make_document(db, created_at=NOW - timedelta(days=3))  # outside window

        stats = compute_stats(db, PERIOD_START, NOW)

        assert stats["documents_filed"] == 2

    def test_meetings_held_vs_upcoming_are_split_by_period_end(self, db):
        make_meeting(db, start_time=NOW - timedelta(hours=2), body="Held Meeting")
        make_meeting(db, start_time=NOW + timedelta(days=3), body="Upcoming Meeting")
        make_meeting(db, start_time=NOW + timedelta(days=30), body="Too Far Out")

        stats = compute_stats(db, PERIOD_START, NOW)

        held_bodies = [m["body"] for m in stats["meetings_held"]]
        upcoming_bodies = [m["body"] for m in stats["meetings_upcoming"]]
        assert held_bodies == ["Held Meeting"]
        assert upcoming_bodies == ["Upcoming Meeting"]

    def test_alerts_grouped_by_level(self, db):
        make_alert(db, alert_level=3, created_at=NOW - timedelta(hours=1))
        make_alert(db, alert_level=3, created_at=NOW - timedelta(hours=2))
        make_alert(db, alert_level=1, created_at=NOW - timedelta(hours=1))
        make_alert(db, alert_level=3, created_at=NOW - timedelta(days=5))  # outside window

        stats = compute_stats(db, PERIOD_START, NOW)

        assert stats["alerts_by_level"] == {"3": 2, "1": 1}
        assert stats["alerts_raised"] == 3

    def test_filing_by_agency_groups_and_sorts_descending(self, db):
        make_document(db, agency="Elections", created_at=NOW - timedelta(hours=1))
        make_document(db, agency="Elections", created_at=NOW - timedelta(hours=2))
        make_document(db, agency="City Clerk", created_at=NOW - timedelta(hours=1))

        stats = compute_stats(db, PERIOD_START, NOW)

        assert stats["filing_by_agency"][0] == {"agency": "Elections", "count": 2}
        assert {"agency": "City Clerk", "count": 1} in stats["filing_by_agency"]

    def test_new_notices_filters_by_document_type(self, db):
        make_document(db, document_type="notice", title="A Notice", created_at=NOW - timedelta(hours=1))
        make_document(db, document_type="agenda", title="An Agenda", created_at=NOW - timedelta(hours=1))

        stats = compute_stats(db, PERIOD_START, NOW)

        titles = [n["title"] for n in stats["new_notices"]]
        assert titles == ["A Notice"]

    def test_new_notices_link_to_the_real_source_when_present(self, db):
        make_document(
            db,
            document_type="notice",
            title="A Notice",
            agency="Elections",
            original_url="https://netfile.com/real-filing",
            created_at=NOW - timedelta(hours=1),
        )

        stats = compute_stats(db, PERIOD_START, NOW)

        assert stats["new_notices"][0]["url"] == "https://netfile.com/real-filing"
        assert stats["new_notices"][0]["meta"] == "Elections"

    def test_new_notices_fall_back_to_an_absolute_dashboard_url_when_no_source_url(self, db, monkeypatch):
        import app.summaries.stats as stats_module

        monkeypatch.setattr(stats_module.settings, "dashboard_base_url", "http://madhatter.local:8010")
        document = make_document(
            db, document_type="notice", title="A Notice", original_url=None, created_at=NOW - timedelta(hours=1)
        )

        stats = compute_stats(db, PERIOD_START, NOW)

        assert stats["new_notices"][0]["url"] == f"http://madhatter.local:8010/documents/{document.id}"

    def test_meeting_links_to_its_agenda_document_when_present(self, db):
        agenda_doc = make_document(db, title="Agenda PDF", original_url="https://example.gov/agenda.pdf")
        make_meeting(db, start_time=NOW - timedelta(hours=1), body="Held Meeting", agenda_document_id=agenda_doc.id)

        stats = compute_stats(db, PERIOD_START, NOW)

        assert stats["meetings_held"][0]["url"] == "https://example.gov/agenda.pdf"

    def test_meeting_prefers_agenda_over_packet_over_minutes(self, db):
        agenda_doc = make_document(db, title="Agenda", original_url="https://example.gov/agenda")
        packet_doc = make_document(db, title="Packet", original_url="https://example.gov/packet")
        make_meeting(
            db,
            start_time=NOW - timedelta(hours=1),
            body="Held Meeting",
            agenda_document_id=agenda_doc.id,
            packet_document_id=packet_doc.id,
        )

        stats = compute_stats(db, PERIOD_START, NOW)

        assert stats["meetings_held"][0]["url"] == "https://example.gov/agenda"

    def test_meeting_url_is_none_when_no_document_is_linked(self, db):
        make_meeting(db, start_time=NOW - timedelta(hours=1), body="Held Meeting")

        stats = compute_stats(db, PERIOD_START, NOW)

        assert stats["meetings_held"][0]["url"] is None

    def test_empty_period_returns_zeroed_stats_not_a_crash(self, db):
        stats = compute_stats(db, PERIOD_START, NOW)

        assert stats["documents_filed"] == 0
        assert stats["meetings_held"] == []
        assert stats["alerts_raised"] == 0
        assert stats["alerts_by_level"] == {}


class TestNextIssueNumber:
    def test_starts_at_one(self, db):
        assert next_issue_number(db, "daily") == 1

    def test_increments_per_existing_row_of_that_period_type(self, db):
        from app.models import NarrativeSummary

        db.add(
            NarrativeSummary(
                period_type="daily",
                period_start=PERIOD_START,
                period_end=NOW,
                title="x",
                narrative_markdown="x",
                model_name="none",
                prompt_version="none",
            )
        )
        db.flush()

        assert next_issue_number(db, "daily") == 2
        assert next_issue_number(db, "weekly") == 1
