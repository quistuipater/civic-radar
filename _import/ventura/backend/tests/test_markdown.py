"""Tests for the Markdown issue-brief exporter (prd.md section 28)."""

from datetime import datetime, timedelta, timezone

from app.export.markdown import _score_label, render_issue_brief
from app.models import IssueEvent, IssueLink

from .conftest import make_document, make_issue


def add_event(db, issue, **overrides):
    defaults = dict(issue_id=issue.id, event_type="notice_posted", title="Something happened")
    defaults.update(overrides)
    event = IssueEvent(**defaults)
    db.add(event)
    db.flush()
    return event


def link_document(db, issue, document=None, **overrides):
    if document is None and "agenda_item_id" not in overrides:
        document = make_document(db)
    defaults = dict(issue_id=issue.id, document_id=document.id if document else None)
    defaults.update(overrides)
    link = IssueLink(**defaults)
    db.add(link)
    db.flush()
    return link


class TestScoreLabel:
    def test_major_at_9_and_above(self):
        assert _score_label(9) == "Major"
        assert _score_label(10) == "Major"

    def test_significant_between_6_and_8(self):
        assert _score_label(6) == "Significant"
        assert _score_label(8) == "Significant"

    def test_moderate_between_3_and_5(self):
        assert _score_label(3) == "Moderate"
        assert _score_label(5) == "Moderate"

    def test_routine_below_3(self):
        assert _score_label(0) == "Routine"
        assert _score_label(2) == "Routine"


class TestRenderIssueBrief:
    def test_renders_title_and_basic_fields(self, db):
        issue = make_issue(db, title="Downtown Parking Ordinance", status="under_review", jurisdiction="City of Ventura")
        db.commit()

        brief = render_issue_brief(db, issue)

        assert "# Downtown Parking Ordinance" in brief
        assert "Status: Under Review" in brief
        assert "Jurisdiction: City of Ventura" in brief

    def test_unknown_jurisdiction_falls_back_to_unknown_label(self, db):
        issue = make_issue(db, jurisdiction=None)
        db.commit()
        assert "Jurisdiction: Unknown" in render_issue_brief(db, issue)

    def test_agencies_involved_are_listed_when_present(self, db):
        issue = make_issue(db, agencies_involved=["City Clerk", "Planning Commission"])
        db.commit()
        assert "Agencies: City Clerk, Planning Commission" in render_issue_brief(db, issue)

    def test_agencies_line_omitted_when_not_set(self, db):
        issue = make_issue(db, agencies_involved=None)
        db.commit()
        assert "Agencies:" not in render_issue_brief(db, issue)

    def test_score_labels_are_rendered_for_all_three_scores(self, db):
        issue = make_issue(db, importance_score=9, urgency_score=5, transparency_risk_score=1)
        db.commit()
        brief = render_issue_brief(db, issue)
        assert "Importance: Major" in brief
        assert "Urgency: Moderate" in brief
        assert "Transparency Risk: Routine" in brief

    def test_review_status_is_title_cased(self, db):
        issue = make_issue(db, review_status="needs_review")
        db.commit()
        assert "Human Review Status: Needs Review" in render_issue_brief(db, issue)

    def test_summary_present_is_used_for_what_happened(self, db):
        issue = make_issue(db, summary="The council is considering a new ordinance.")
        db.commit()
        assert "The council is considering a new ordinance." in render_issue_brief(db, issue)

    def test_no_summary_uses_placeholder(self, db):
        issue = make_issue(db, summary=None)
        db.commit()
        assert "_No summary recorded yet._" in render_issue_brief(db, issue)

    def test_events_section_omitted_when_no_events(self, db):
        issue = make_issue(db)
        db.commit()
        assert "What Changed Recently" not in render_issue_brief(db, issue)

    def test_events_are_sorted_newest_first(self, db):
        issue = make_issue(db)
        add_event(db, issue, title="Older event", event_date=datetime.now(timezone.utc) - timedelta(days=10))
        add_event(db, issue, title="Newer event", event_date=datetime.now(timezone.utc) - timedelta(days=1))
        db.commit()

        brief = render_issue_brief(db, issue)

        assert brief.index("Newer event") < brief.index("Older event")

    def test_events_are_capped_at_5(self, db):
        issue = make_issue(db)
        for i in range(7):
            add_event(db, issue, title=f"Event {i}", event_date=datetime.now(timezone.utc) - timedelta(days=i))
        db.commit()

        brief = render_issue_brief(db, issue)

        assert sum(1 for line in brief.splitlines() if line.startswith("- ")) <= 5 + 10  # events + doc links headroom
        assert "Event 6" not in brief  # the 7th-oldest should have been dropped by the cap

    def test_event_with_no_event_date_shows_date_unknown(self, db):
        issue = make_issue(db)
        add_event(db, issue, title="Undated event", event_date=None)
        db.commit()
        assert "date unknown: Undated event" in render_issue_brief(db, issue)

    def test_next_deadline_present(self, db):
        issue = make_issue(db, next_deadline=datetime(2026, 8, 1, tzinfo=timezone.utc))
        db.commit()
        assert "Next deadline: 2026-08-01" in render_issue_brief(db, issue)

    def test_no_next_deadline_shows_placeholder(self, db):
        issue = make_issue(db, next_deadline=None)
        db.commit()
        assert "No upcoming deadline recorded." in render_issue_brief(db, issue)

    def test_key_documents_section_omitted_when_no_links(self, db):
        issue = make_issue(db)
        db.commit()
        assert "Key Documents" not in render_issue_brief(db, issue)

    def test_linked_document_is_listed_with_title_and_url(self, db):
        issue = make_issue(db)
        document = make_document(db, title="June Agenda", original_url="https://example.invalid/agenda")
        link_document(db, issue, document)
        db.commit()

        brief = render_issue_brief(db, issue)

        assert "[June Agenda](https://example.invalid/agenda)" in brief

    def test_linked_document_falls_back_to_document_type_when_no_title(self, db):
        issue = make_issue(db)
        document = make_document(db, title=None, document_type="agenda", original_url="https://example.invalid/a")
        link_document(db, issue, document)
        db.commit()

        assert "[agenda]" in render_issue_brief(db, issue)

    def test_linked_document_url_falls_back_to_archive_path(self, db):
        issue = make_issue(db)
        document = make_document(db, title="Doc", original_url=None, archive_path="/archive/doc.pdf")
        link_document(db, issue, document)
        db.commit()

        assert "[Doc](/archive/doc.pdf)" in render_issue_brief(db, issue)

    def test_links_with_no_document_id_are_excluded_from_key_documents(self, db):
        issue = make_issue(db)
        link_document(db, issue, document=None, agenda_item_id=None, document_id=None)
        db.commit()

        # Only IssueLinks with a document_id are ever queried for this
        # section (agenda-item-only links go through a different surface).
        assert "Key Documents" not in render_issue_brief(db, issue)

    def test_assessment_section_reuses_summary_when_present(self, db):
        issue = make_issue(db, summary="The specific assessment text.")
        db.commit()
        brief = render_issue_brief(db, issue)
        assert brief.count("The specific assessment text.") == 2  # both "What Happened" and "Assessment"

    def test_assessment_section_uses_unreviewed_placeholder_when_no_summary(self, db):
        issue = make_issue(db, summary=None)
        db.commit()
        assert "has not yet been assessed by a human reviewer" in render_issue_brief(db, issue)
