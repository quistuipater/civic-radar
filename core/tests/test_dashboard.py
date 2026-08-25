"""Tests for the server-rendered dashboard routes. classify_document_form
calls the real classify_document -- safe without mocking since the test DB
has no seeded Prompt rows, so it deterministically takes the heuristic path
(same reasoning as the REST router tests).
"""

from datetime import date, datetime, timedelta, timezone

import app.dashboard as dashboard_module
from app.models import Issue, IssueLink, ManualSubmission

from .conftest import (
    make_agenda_item,
    make_ai_output,
    make_alert,
    make_document,
    make_issue,
    make_meeting,
    make_meeting_transcript,
    make_source,
)


class TestHomePage:
    def test_renders_with_data(self, db, client):
        make_alert(db, alert_level=4, title="Urgent Alert")
        make_source(db, consecutive_failures=5)
        make_document(db, document_type="notice", title="Newest Notice")
        make_meeting(db, start_time=datetime.now(timezone.utc) + timedelta(days=2))
        db.commit()

        resp = client.get("/")

        assert resp.status_code == 200
        assert "Urgent Alert" in resp.text
        assert "Newest Notice" in resp.text

    def test_snapshot_documents_are_excluded_from_newest_documents(self, db, client):
        make_document(db, document_type="source_page_snapshot", title="A Snapshot")
        db.commit()

        resp = client.get("/")

        assert "A Snapshot" not in resp.text


class TestReviewQueuePage:
    def test_renders_with_flagged_items(self, db, client):
        make_alert(db, alert_level=4, title="Needs Review", reviewed=False)
        db.commit()

        resp = client.get("/review-queue")

        assert resp.status_code == 200
        assert "Needs Review" in resp.text


class TestDashboardApproveReject:
    def test_approve_marks_alert_reviewed_and_redirects(self, db, client):
        alert = make_alert(db, reviewed=False)
        db.commit()

        resp = client.post(f"/review/{alert.id}/approve", follow_redirects=False)

        assert resp.status_code == 303
        assert resp.headers["location"] == "/review-queue"
        db.refresh(alert)
        assert alert.reviewed is True
        assert alert.status == "approved"

    def test_reject_marks_alert_reviewed_and_redirects(self, db, client):
        alert = make_alert(db, reviewed=False)
        db.commit()

        resp = client.post(f"/review/{alert.id}/reject", follow_redirects=False)

        assert resp.status_code == 303
        db.refresh(alert)
        assert alert.status == "rejected"

    def test_approve_unknown_id_redirects_without_error(self, client):
        resp = client.post(
            "/review/00000000-0000-0000-0000-000000000000/approve", follow_redirects=False
        )
        assert resp.status_code == 303


class TestIssueListPage:
    def test_renders_with_issues(self, db, client):
        make_issue(db, title="Downtown Parking Ordinance")
        db.commit()

        resp = client.get("/issues")

        assert resp.status_code == 200
        assert "Downtown Parking Ordinance" in resp.text


class TestCreateIssueForm:
    def test_creates_an_issue_and_redirects(self, db, client):
        resp = client.post(
            "/issues/new",
            data={"title": "New Issue", "slug": "new-issue-form", "jurisdiction": "City of Ventura"},
            follow_redirects=False,
        )

        assert resp.status_code == 303
        assert resp.headers["location"] == "/issues"
        assert db.query(Issue).filter_by(slug="new-issue-form").one().title == "New Issue"

    def test_duplicate_slug_does_not_create_a_second_issue(self, db, client):
        make_issue(db, slug="taken-slug")
        db.commit()

        client.post("/issues/new", data={"title": "Different Title", "slug": "taken-slug"}, follow_redirects=False)

        assert db.query(Issue).filter_by(slug="taken-slug").count() == 1

    def test_blank_optional_fields_are_stored_as_null(self, db, client):
        client.post(
            "/issues/new", data={"title": "Minimal Issue", "slug": "minimal-issue", "jurisdiction": "", "summary": ""}
        )
        issue = db.query(Issue).filter_by(slug="minimal-issue").one()
        assert issue.jurisdiction is None
        assert issue.summary is None


class TestIssueDetailPage:
    def test_returns_404_for_unknown_issue(self, client):
        resp = client.get("/issues/00000000-0000-0000-0000-000000000000")
        assert resp.status_code == 404

    def test_renders_with_linked_documents(self, db, client):
        issue = make_issue(db, title="Findable Issue")
        document = make_document(db, title="Linked Doc")
        db.add(IssueLink(issue_id=issue.id, document_id=document.id))
        db.commit()

        resp = client.get(f"/issues/{issue.id}")

        assert resp.status_code == 200
        assert "Findable Issue" in resp.text
        assert "Linked Doc" in resp.text


class TestIssueBriefRedirect:
    def test_redirects_to_the_api_endpoint(self, db, client):
        issue = make_issue(db)
        db.commit()

        resp = client.get(f"/issues/{issue.id}/brief.md", follow_redirects=False)

        assert resp.status_code == 307 or resp.status_code == 302
        assert resp.headers["location"] == f"/api/issues/{issue.id}/brief.md"


class TestMeetingDetailPage:
    def test_returns_404_for_unknown_meeting(self, client):
        resp = client.get("/meetings/00000000-0000-0000-0000-000000000000")
        assert resp.status_code == 404

    def test_renders_with_matching_documents_and_agenda_items(self, db, client):
        meeting = make_meeting(db, body="City Council", start_time=datetime(2026, 6, 1, tzinfo=timezone.utc))
        make_document(db, body="City Council", meeting_date=datetime(2026, 6, 1).date(), title="June Agenda")
        make_agenda_item(db, meeting=meeting, title="Budget Item")
        db.commit()

        resp = client.get(f"/meetings/{meeting.id}")

        assert resp.status_code == 200
        assert "June Agenda" in resp.text
        assert "Budget Item" in resp.text

    def test_links_to_the_specific_agenda_and_minutes_documents(self, db, client):
        agenda_doc = make_document(db, title="Real Agenda PDF", document_type="agenda")
        minutes_doc = make_document(db, title="Real Minutes PDF", document_type="minutes")
        meeting = make_meeting(
            db, body="City Council", agenda_document_id=agenda_doc.id, minutes_document_id=minutes_doc.id
        )
        db.commit()

        resp = client.get(f"/meetings/{meeting.id}")

        assert f'href="/documents/{agenda_doc.id}"' in resp.text
        assert f'href="/documents/{minutes_doc.id}"' in resp.text

    def test_shows_meeting_results_summary_when_available(self, db, client):
        minutes_doc = make_document(db, document_type="minutes")
        meeting = make_meeting(db, minutes_document_id=minutes_doc.id)
        make_ai_output(
            db,
            minutes_doc.id,
            task_type="meeting_results_summary",
            output_json={
                "overall_summary": "The council approved the budget amendment.",
                "key_decisions": [{"topic": "Budget amendment", "outcome": "approved", "vote_tally": "4-1", "notes": None}],
            },
        )
        db.commit()

        resp = client.get(f"/meetings/{meeting.id}")

        assert "The council approved the budget amendment." in resp.text
        assert "Budget amendment" in resp.text
        assert "4-1" in resp.text

    def test_shows_not_yet_summarized_when_minutes_exist_without_a_summary(self, db, client):
        minutes_doc = make_document(db, document_type="minutes")
        meeting = make_meeting(db, minutes_document_id=minutes_doc.id)
        db.commit()

        resp = client.get(f"/meetings/{meeting.id}")

        assert "haven&#39;t been summarized yet" in resp.text or "haven't been summarized yet" in resp.text

    def test_shows_linked_meeting_audio_with_a_link_to_the_full_transcript(self, db, client):
        meeting = make_meeting(db, body="City Council")
        transcript = make_meeting_transcript(
            db, meeting=meeting, title="City Council Meeting - July 7, 2026", duration_seconds=125.0, speaker_count=3
        )
        db.commit()

        resp = client.get(f"/meetings/{meeting.id}")

        assert "City Council Meeting - July 7, 2026" in resp.text
        assert f'href="/transcripts/{transcript.id}"' in resp.text
        assert "2:05" in resp.text  # 125 seconds
        assert "3" in resp.text  # speaker_count

    def test_no_meeting_audio_section_when_there_are_no_transcripts(self, db, client):
        meeting = make_meeting(db, body="City Council")
        db.commit()

        resp = client.get(f"/meetings/{meeting.id}")

        assert "Meeting Audio" not in resp.text


class TestTranscriptDetailPage:
    def test_returns_404_for_unknown_transcript(self, client):
        resp = client.get("/transcripts/00000000-0000-0000-0000-000000000000")
        assert resp.status_code == 404

    def test_renders_transcript_with_segments_and_linked_meeting(self, db, client):
        meeting = make_meeting(db, body="City Council")
        transcript = make_meeting_transcript(
            db,
            meeting=meeting,
            title="City Council Meeting - July 7, 2026",
            segments=[
                {"start": 0.0, "end": 5.0, "text": "Good evening everyone.", "speaker": "SPEAKER_00"},
                {"start": 65.0, "end": 70.0, "text": "Motion carries five to zero.", "speaker": "SPEAKER_02"},
            ],
        )
        db.commit()

        resp = client.get(f"/transcripts/{transcript.id}")

        assert resp.status_code == 200
        assert "Good evening everyone." in resp.text
        assert "Motion carries five to zero." in resp.text
        assert "SPEAKER_00" in resp.text
        assert f'href="/meetings/{meeting.id}"' in resp.text

    def test_renders_without_a_linked_meeting(self, db, client):
        transcript = make_meeting_transcript(db, meeting=None)
        db.commit()

        resp = client.get(f"/transcripts/{transcript.id}")

        assert resp.status_code == 200
        assert "not linked to a specific meeting" in resp.text


class TestAgendaItemDetailPage:
    def test_returns_404_for_unknown_item(self, client):
        resp = client.get("/agenda-items/00000000-0000-0000-0000-000000000000")
        assert resp.status_code == 404

    def test_renders_with_its_meeting(self, db, client):
        meeting = make_meeting(db, body="Planning Commission")
        item = make_agenda_item(db, meeting=meeting, title="Zoning Variance")
        db.commit()

        resp = client.get(f"/agenda-items/{item.id}")

        assert resp.status_code == 200
        assert "Zoning Variance" in resp.text
        assert "Planning Commission" in resp.text

    def test_links_to_the_meetings_agenda_and_minutes_documents(self, db, client):
        agenda_doc = make_document(db, document_type="agenda")
        minutes_doc = make_document(db, document_type="minutes")
        meeting = make_meeting(db, agenda_document_id=agenda_doc.id, minutes_document_id=minutes_doc.id)
        item = make_agenda_item(db, meeting=meeting, title="Zoning Variance")
        db.commit()

        resp = client.get(f"/agenda-items/{item.id}")

        assert f'href="/documents/{agenda_doc.id}"' in resp.text
        assert f'href="/documents/{minutes_doc.id}"' in resp.text

    def test_shows_meeting_results_summary_when_available(self, db, client):
        minutes_doc = make_document(db, document_type="minutes")
        meeting = make_meeting(db, minutes_document_id=minutes_doc.id)
        item = make_agenda_item(db, meeting=meeting, title="Approval of the Minutes")
        make_ai_output(
            db,
            minutes_doc.id,
            task_type="meeting_results_summary",
            output_json={"overall_summary": "The committee approved the minutes as presented.", "key_decisions": []},
        )
        db.commit()

        resp = client.get(f"/agenda-items/{item.id}")

        assert "The committee approved the minutes as presented." in resp.text

    def test_no_source_document_links_shown_when_meeting_has_none_linked(self, db, client):
        item = make_agenda_item(db, title="Standalone Item")
        db.commit()

        resp = client.get(f"/agenda-items/{item.id}")

        assert resp.status_code == 200
        assert "Source:" not in resp.text

    def test_approval_of_minutes_item_links_to_the_specific_dates_it_references(self, db, client):
        # Regression case: this exact item genuinely occurred in the DB --
        # "Approval of the Minutes" for the Historic Preservation Committee,
        # referencing "April 9 and June 11, 2026" in its own description,
        # where only April 9's minutes had actually been archived.
        meeting = make_meeting(db, body="Historic Preservation Committee")
        archived_minutes = make_document(
            db, body="Historic Preservation Committee", document_type="minutes", meeting_date=date(2026, 4, 9)
        )
        item = make_agenda_item(
            db,
            meeting=meeting,
            title="Approval of the Minutes",
            description="Approval of the draft minutes from the April 9 and June 11, 2026 meetings.",
        )
        db.commit()

        resp = client.get(f"/agenda-items/{item.id}")

        assert "Minutes being approved:" in resp.text
        assert f'href="/documents/{archived_minutes.id}"' in resp.text
        assert "2026-04-09" in resp.text
        assert "2026-06-11 (not yet archived)" in resp.text

    def test_non_minutes_items_never_trigger_the_referenced_date_lookup(self, db, client):
        meeting = make_meeting(db, body="City Council")
        item = make_agenda_item(
            db, meeting=meeting, title="Zoning Variance", description="Continued from the May 14, 2026 hearing."
        )
        db.commit()

        resp = client.get(f"/agenda-items/{item.id}")

        assert "Minutes being approved:" not in resp.text

    def test_minutes_item_with_no_dates_in_description_shows_nothing_extra(self, db, client):
        meeting = make_meeting(db, body="City Council")
        item = make_agenda_item(db, meeting=meeting, title="Approval of the Minutes", description="No dates mentioned.")
        db.commit()

        resp = client.get(f"/agenda-items/{item.id}")

        assert "Minutes being approved:" not in resp.text


class TestReferencedMinutesDocuments:
    """Direct tests of the date-parsing edge cases -- no year stated
    anywhere, an invalid calendar date, and a duplicate mention -- rather
    than routing all three through the full HTTP stack.
    """

    def test_date_with_no_year_anywhere_in_the_text_is_skipped(self, db):
        meeting = make_meeting(db, body="City Council")
        item = make_agenda_item(db, meeting=meeting, title="Approval of the Minutes", description="From the April 9 meeting.")
        db.commit()

        assert dashboard_module._referenced_minutes_documents(db, item, meeting) == []

    def test_invalid_calendar_date_is_skipped_not_crashed_on(self, db):
        meeting = make_meeting(db, body="City Council")
        item = make_agenda_item(
            db, meeting=meeting, title="Approval of the Minutes", description="From the February 30, 2026 meeting."
        )
        db.commit()

        assert dashboard_module._referenced_minutes_documents(db, item, meeting) == []

    def test_duplicate_date_mention_is_deduplicated(self, db):
        meeting = make_meeting(db, body="City Council")
        item = make_agenda_item(
            db,
            meeting=meeting,
            title="Approval of the Minutes",
            description="From the April 9, 2026 meeting (April 9, 2026).",
        )
        db.commit()

        results = dashboard_module._referenced_minutes_documents(db, item, meeting)

        assert len(results) == 1


class TestDocumentDetailPage:
    def test_returns_404_for_unknown_document(self, client):
        resp = client.get("/documents/00000000-0000-0000-0000-000000000000")
        assert resp.status_code == 404

    def test_renders_with_issue_links_and_all_issues_dropdown(self, db, client):
        document = make_document(db, title="Findable Document")
        issue = make_issue(db, title="Related Issue")
        db.add(IssueLink(issue_id=issue.id, document_id=document.id))
        db.commit()

        resp = client.get(f"/documents/{document.id}")

        assert resp.status_code == 200
        assert "Findable Document" in resp.text
        assert "Related Issue" in resp.text

    def test_shows_acknowledge_action_for_unreviewed_flagged_output(self, db, client):
        document = make_document(db)
        make_ai_output(db, document.id, output_json={"human_review_required": True})
        db.commit()

        resp = client.get(f"/documents/{document.id}")

        assert resp.status_code == 200
        assert "needs review" in resp.text
        assert "Mark reviewed" in resp.text

    def test_shows_reviewed_status_instead_of_action_once_acknowledged(self, db, client):
        document = make_document(db)
        make_ai_output(
            db,
            document.id,
            output_json={"human_review_required": True},
            reviewed=True,
            operator_note="looks fine",
        )
        db.commit()

        resp = client.get(f"/documents/{document.id}")

        assert resp.status_code == 200
        assert "Mark reviewed" not in resp.text
        assert "Reviewed" in resp.text
        assert "looks fine" in resp.text

    def test_no_review_action_for_output_not_flagged(self, db, client):
        document = make_document(db)
        make_ai_output(db, document.id, output_json={"human_review_required": False})
        db.commit()

        resp = client.get(f"/documents/{document.id}")

        assert resp.status_code == 200
        # The "Correct this document" panel's help text legitimately mentions
        # "needs review" (it explains what saving a correction clears)
        # regardless of this AI output's own flag, so check for the AI
        # output's own review badge specifically rather than the bare phrase.
        assert '<span class="badge level-3">needs review</span>' not in resp.text
        assert "Mark reviewed" not in resp.text


class TestAcknowledgeAiOutputForm:
    def test_marks_output_reviewed_and_redirects(self, db, client):
        document = make_document(db)
        output = make_ai_output(db, document.id, output_json={"human_review_required": True})
        db.commit()

        resp = client.post(
            f"/documents/{document.id}/ai-outputs/{output.id}/acknowledge",
            data={"operator_note": "checked against agenda"},
            follow_redirects=False,
        )

        assert resp.status_code == 303
        assert resp.headers["location"] == f"/documents/{document.id}"
        db.refresh(output)
        assert output.reviewed is True
        assert output.operator_note == "checked against agenda"

    def test_unknown_output_still_redirects_without_error(self, db, client):
        document = make_document(db)
        db.commit()

        resp = client.post(
            f"/documents/{document.id}/ai-outputs/00000000-0000-0000-0000-000000000000/acknowledge",
            follow_redirects=False,
        )

        assert resp.status_code == 303

    def test_output_belonging_to_a_different_document_is_not_acknowledged(self, db, client):
        document = make_document(db)
        other_document = make_document(db)
        output = make_ai_output(db, other_document.id, output_json={"human_review_required": True})
        db.commit()

        resp = client.post(
            f"/documents/{document.id}/ai-outputs/{output.id}/acknowledge", follow_redirects=False
        )

        assert resp.status_code == 303
        db.refresh(output)
        assert output.reviewed is False


class TestClassifyDocumentForm:
    def test_triggers_classification_and_redirects(self, db, client):
        document = make_document(db, title="An ordinance about coastal development")
        db.commit()

        resp = client.post(f"/documents/{document.id}/classify", follow_redirects=False)

        assert resp.status_code == 303
        assert resp.headers["location"] == f"/documents/{document.id}"

    def test_unknown_document_still_redirects_without_error(self, client):
        resp = client.post(
            "/documents/00000000-0000-0000-0000-000000000000/classify", follow_redirects=False
        )
        assert resp.status_code == 303


class TestAttachIssueForm:
    def test_attaches_document_to_issue(self, db, client):
        document = make_document(db)
        issue = make_issue(db)
        db.commit()

        resp = client.post(
            f"/documents/{document.id}/attach-issue", data={"issue_id": str(issue.id)}, follow_redirects=False
        )

        assert resp.status_code == 303
        assert db.query(IssueLink).filter_by(document_id=document.id, issue_id=issue.id).count() == 1

    def test_reattaching_the_same_issue_does_not_create_a_duplicate_link(self, db, client):
        document = make_document(db)
        issue = make_issue(db)
        db.add(IssueLink(issue_id=issue.id, document_id=document.id))
        db.commit()

        client.post(f"/documents/{document.id}/attach-issue", data={"issue_id": str(issue.id)})

        assert db.query(IssueLink).filter_by(document_id=document.id, issue_id=issue.id).count() == 1


class TestManualSubmissionFormPage:
    def test_renders(self, client):
        resp = client.get("/manual-submissions/new")
        assert resp.status_code == 200


class TestCreateManualSubmissionForm:
    def test_creates_an_unverified_submission_and_redirects(self, db, client):
        resp = client.post(
            "/manual-submissions/new",
            data={"submission_type": "text", "claimed_source": "Nextdoor", "content_text": "Someone said..."},
            follow_redirects=False,
        )

        assert resp.status_code == 303
        assert resp.headers["location"] == "/review-queue"
        submission = db.query(ManualSubmission).filter_by(claimed_source="Nextdoor").one()
        assert submission.verified is False
        assert submission.verification_status == "unresolved"

    def test_blank_optional_fields_are_stored_as_null(self, db, client):
        client.post("/manual-submissions/new", data={"submission_type": "text"})
        submission = db.query(ManualSubmission).filter_by(submission_type="text").one()
        assert submission.claimed_source is None
        assert submission.content_text is None
