"""Tests for the daily digest rollup: build_daily_digest's seven section
queries (each has its own window/filter logic) and render_digest_markdown's
per-section rendering, both populated and empty.
"""

from datetime import date, datetime, timedelta, timezone

from app.export.digest import build_daily_digest, render_digest_markdown

from .conftest import make_agenda_item, make_ai_output, make_alert, make_document, make_manual_submission, make_meeting


def hours_ago(n):
    return datetime.now(timezone.utc) - timedelta(hours=n)


def days_from_today(n):
    return date.today() + timedelta(days=n)


class TestBuildDailyDigestTopChanges:
    def test_includes_recent_level_3_plus_alerts(self, db):
        make_alert(db, alert_level=4, created_at=hours_ago(1))
        db.commit()
        digest = build_daily_digest(db)
        assert len(digest["top_changes"]) == 1

    def test_excludes_alerts_below_level_3(self, db):
        make_alert(db, alert_level=2, created_at=hours_ago(1))
        db.commit()
        digest = build_daily_digest(db)
        assert digest["top_changes"] == []

    def test_excludes_alerts_outside_the_window(self, db):
        make_alert(db, alert_level=4, created_at=hours_ago(48))
        db.commit()
        digest = build_daily_digest(db, window_hours=24)
        assert digest["top_changes"] == []


class TestBuildDailyDigestUpcomingHearings:
    def test_includes_hearing_within_14_days(self, db):
        meeting = make_meeting(db, start_time=datetime.now(timezone.utc) + timedelta(days=5))
        make_agenda_item(db, meeting=meeting, public_hearing=True)
        db.commit()
        digest = build_daily_digest(db)
        assert len(digest["upcoming_hearings"]) == 1

    def test_includes_vote_expected_item_even_without_hearing_flag(self, db):
        meeting = make_meeting(db, start_time=datetime.now(timezone.utc) + timedelta(days=5))
        make_agenda_item(db, meeting=meeting, public_hearing=False, vote_expected=True)
        db.commit()
        digest = build_daily_digest(db)
        assert len(digest["upcoming_hearings"]) == 1

    def test_excludes_items_with_neither_flag(self, db):
        meeting = make_meeting(db, start_time=datetime.now(timezone.utc) + timedelta(days=5))
        make_agenda_item(db, meeting=meeting, public_hearing=False, vote_expected=False)
        db.commit()
        digest = build_daily_digest(db)
        assert digest["upcoming_hearings"] == []

    def test_excludes_meetings_beyond_14_days(self, db):
        meeting = make_meeting(db, start_time=datetime.now(timezone.utc) + timedelta(days=30))
        make_agenda_item(db, meeting=meeting, public_hearing=True)
        db.commit()
        digest = build_daily_digest(db)
        assert digest["upcoming_hearings"] == []

    def test_excludes_meetings_in_the_past(self, db):
        meeting = make_meeting(db, start_time=datetime.now(timezone.utc) - timedelta(days=1))
        make_agenda_item(db, meeting=meeting, public_hearing=True)
        db.commit()
        digest = build_daily_digest(db)
        assert digest["upcoming_hearings"] == []


class TestBuildDailyDigestNotices:
    def test_includes_recent_notices(self, db):
        make_document(db, document_type="notice", created_at=hours_ago(1))
        db.commit()
        digest = build_daily_digest(db)
        assert len(digest["new_notices"]) == 1

    def test_excludes_other_document_types(self, db):
        make_document(db, document_type="agenda", created_at=hours_ago(1))
        db.commit()
        digest = build_daily_digest(db)
        assert digest["new_notices"] == []


class TestBuildDailyDigestCampaignItems:
    def test_includes_recent_campaign_finance_documents(self, db):
        make_document(db, agency="Elections / Campaign Finance", created_at=hours_ago(1))
        db.commit()
        digest = build_daily_digest(db)
        assert len(digest["new_campaign_items"]) == 1

    def test_excludes_documents_from_other_agencies(self, db):
        make_document(db, agency="City Clerk", created_at=hours_ago(1))
        db.commit()
        digest = build_daily_digest(db)
        assert digest["new_campaign_items"] == []


class TestBuildDailyDigestNeedsReview:
    def test_includes_recent_classifications_requiring_human_review(self, db):
        document = make_document(db)
        make_ai_output(
            db,
            document.id,
            task_type="classification",
            output_json={"human_review_required": True},
            created_at=hours_ago(1),
        )
        db.commit()
        digest = build_daily_digest(db)
        assert len(digest["needs_review"]) == 1

    def test_excludes_classifications_not_requiring_review(self, db):
        document = make_document(db)
        make_ai_output(
            db,
            document.id,
            task_type="classification",
            output_json={"human_review_required": False},
            created_at=hours_ago(1),
        )
        db.commit()
        digest = build_daily_digest(db)
        assert digest["needs_review"] == []

    def test_excludes_non_classification_task_types(self, db):
        document = make_document(db)
        make_ai_output(
            db,
            document.id,
            task_type="summarization",
            output_json={"human_review_required": True},
            created_at=hours_ago(1),
        )
        db.commit()
        digest = build_daily_digest(db)
        assert digest["needs_review"] == []

    def test_excludes_already_reviewed_classifications(self, db):
        document = make_document(db)
        make_ai_output(
            db,
            document.id,
            task_type="classification",
            output_json={"human_review_required": True},
            reviewed=True,
            created_at=hours_ago(1),
        )
        db.commit()
        digest = build_daily_digest(db)
        assert digest["needs_review"] == []


class TestBuildDailyDigestApproachingDeadlines:
    def test_includes_deadline_within_14_days(self, db):
        make_document(db, comment_deadline=days_from_today(5))
        db.commit()
        digest = build_daily_digest(db)
        assert len(digest["approaching_deadlines"]) == 1

    def test_excludes_deadline_beyond_14_days(self, db):
        make_document(db, comment_deadline=days_from_today(30))
        db.commit()
        digest = build_daily_digest(db)
        assert digest["approaching_deadlines"] == []

    def test_excludes_deadline_already_passed(self, db):
        make_document(db, comment_deadline=days_from_today(-1))
        db.commit()
        digest = build_daily_digest(db)
        assert digest["approaching_deadlines"] == []

    def test_excludes_documents_with_no_deadline(self, db):
        make_document(db, comment_deadline=None)
        db.commit()
        digest = build_daily_digest(db)
        assert digest["approaching_deadlines"] == []

    def test_includes_public_hearing_date_within_14_days(self, db):
        make_document(db, public_hearing_date=days_from_today(5))
        db.commit()
        digest = build_daily_digest(db)
        assert len(digest["approaching_deadlines"]) == 1

    def test_excludes_public_hearing_date_beyond_14_days(self, db):
        make_document(db, public_hearing_date=days_from_today(30))
        db.commit()
        digest = build_daily_digest(db)
        assert digest["approaching_deadlines"] == []

    def test_document_with_only_comment_deadline_is_labeled_comment_deadline(self, db):
        make_document(db, comment_deadline=days_from_today(5), public_hearing_date=None)
        db.commit()
        digest = build_daily_digest(db)
        _, deadline_date, kind = digest["approaching_deadlines"][0]
        assert kind == "comment deadline"
        assert deadline_date == days_from_today(5)

    def test_document_with_only_public_hearing_date_is_labeled_hearing(self, db):
        make_document(db, comment_deadline=None, public_hearing_date=days_from_today(5))
        db.commit()
        digest = build_daily_digest(db)
        _, deadline_date, kind = digest["approaching_deadlines"][0]
        assert kind == "hearing"

    def test_document_with_both_fields_in_window_surfaces_the_sooner_one(self, db):
        make_document(db, comment_deadline=days_from_today(10), public_hearing_date=days_from_today(3))
        db.commit()
        digest = build_daily_digest(db)
        _, deadline_date, kind = digest["approaching_deadlines"][0]
        assert deadline_date == days_from_today(3)
        assert kind == "hearing"

    def test_document_with_comment_deadline_in_window_and_hearing_date_far_outside_only_uses_the_in_window_one(self, db):
        make_document(db, comment_deadline=days_from_today(5), public_hearing_date=days_from_today(60))
        db.commit()
        digest = build_daily_digest(db)
        _, deadline_date, kind = digest["approaching_deadlines"][0]
        assert kind == "comment deadline"
        assert deadline_date == days_from_today(5)

    def test_results_are_sorted_soonest_first_across_documents(self, db):
        make_document(db, title="Later", comment_deadline=days_from_today(10))
        make_document(db, title="Sooner", public_hearing_date=days_from_today(2))
        db.commit()
        digest = build_daily_digest(db)
        titles = [doc.title for doc, _, _ in digest["approaching_deadlines"]]
        assert titles == ["Sooner", "Later"]


class TestBuildDailyDigestLowConfidenceAndUnverified:
    def test_includes_recent_low_confidence_classifications(self, db):
        document = make_document(db)
        make_ai_output(db, document.id, task_type="classification", confidence="low", created_at=hours_ago(1))
        db.commit()
        digest = build_daily_digest(db)
        assert len(digest["low_confidence"]) == 1

    def test_excludes_high_confidence_classifications(self, db):
        document = make_document(db)
        make_ai_output(db, document.id, task_type="classification", confidence="high", created_at=hours_ago(1))
        db.commit()
        digest = build_daily_digest(db)
        assert digest["low_confidence"] == []

    def test_includes_recent_unresolved_manual_submissions(self, db):
        make_manual_submission(db, verification_status="unresolved", submitted_at=hours_ago(1))
        db.commit()
        digest = build_daily_digest(db)
        assert len(digest["unverified_submissions"]) == 1

    def test_excludes_resolved_manual_submissions(self, db):
        make_manual_submission(db, verification_status="confirmed", submitted_at=hours_ago(1))
        db.commit()
        digest = build_daily_digest(db)
        assert digest["unverified_submissions"] == []


class TestRenderDigestMarkdown:
    def test_empty_digest_renders_all_empty_state_messages(self, db):
        digest = build_daily_digest(db)
        markdown = render_digest_markdown(digest)

        assert "No level 3+ alerts in this window" in markdown
        assert "None scheduled in the next 14 days" in markdown
        assert markdown.count("None in this window") >= 3
        assert "None flagged in this window" in markdown

    def test_top_change_uses_trigger_reason_when_present(self, db):
        make_alert(db, alert_level=4, trigger_reason="hearing expected", summary="fallback summary")
        db.commit()
        markdown = render_digest_markdown(build_daily_digest(db))
        assert "hearing expected" in markdown
        assert "fallback summary" not in markdown

    def test_top_change_falls_back_to_summary_when_no_trigger_reason(self, db):
        make_alert(db, alert_level=4, trigger_reason=None, summary="fallback summary")
        db.commit()
        markdown = render_digest_markdown(build_daily_digest(db))
        assert "fallback summary" in markdown

    def test_upcoming_hearing_labels_public_hearing_vs_vote(self, db):
        meeting = make_meeting(db, start_time=datetime.now(timezone.utc) + timedelta(days=3), body="City Council")
        make_agenda_item(db, meeting=meeting, title="Zoning Item", public_hearing=True)
        db.commit()
        markdown = render_digest_markdown(build_daily_digest(db))
        assert "(hearing)" in markdown
        assert "Zoning Item" in markdown
        assert "City Council" in markdown

    def test_notice_renders_as_a_markdown_link(self, db):
        make_document(db, document_type="notice", title="Public Notice of Hearing", original_url="https://example.invalid/n")
        db.commit()
        markdown = render_digest_markdown(build_daily_digest(db))
        assert "[Public Notice of Hearing](https://example.invalid/n)" in markdown

    def test_untitled_document_renders_with_placeholder_title(self, db):
        make_document(db, document_type="notice", title=None, original_url="https://example.invalid/n")
        db.commit()
        markdown = render_digest_markdown(build_daily_digest(db))
        assert "(untitled)" in markdown

    def test_campaign_item_renders_as_a_markdown_link(self, db):
        make_document(
            db,
            agency="Elections / Campaign Finance",
            title="Form 460 Filing",
            original_url="https://example.invalid/f460",
        )
        db.commit()
        markdown = render_digest_markdown(build_daily_digest(db))
        assert "[Form 460 Filing](https://example.invalid/f460)" in markdown

    def test_needs_review_item_links_to_the_document_detail_page(self, db):
        document = make_document(db, title="Flagged Document")
        make_ai_output(db, document.id, task_type="classification", output_json={"human_review_required": True})
        db.commit()
        markdown = render_digest_markdown(build_daily_digest(db))
        assert f"[Flagged Document](/documents/{document.id})" in markdown

    def test_approaching_deadline_renders_with_the_deadline_date_and_kind(self, db):
        make_document(db, title="Comment Period Item", comment_deadline=days_from_today(5))
        db.commit()
        markdown = render_digest_markdown(build_daily_digest(db))
        assert f"{days_from_today(5).isoformat()} (comment deadline): [Comment Period Item]" in markdown

    def test_approaching_hearing_date_renders_with_hearing_label(self, db):
        make_document(db, title="Zoning Hearing Item", public_hearing_date=days_from_today(5))
        db.commit()
        markdown = render_digest_markdown(build_daily_digest(db))
        assert f"{days_from_today(5).isoformat()} (hearing): [Zoning Hearing Item]" in markdown

    def test_low_confidence_and_unverified_can_coexist(self, db):
        document = make_document(db, title="Shaky Classification")
        make_ai_output(db, document.id, task_type="classification", confidence="low")
        make_manual_submission(db, verification_status="unresolved", claimed_source="Nextdoor", content_text="something")
        db.commit()
        markdown = render_digest_markdown(build_daily_digest(db))
        assert "Shaky Classification" in markdown
        assert "Nextdoor" in markdown

    def test_unverified_submission_content_is_truncated_to_120_chars(self, db):
        make_manual_submission(db, verification_status="unresolved", claimed_source="Facebook", content_text="z" * 500)
        db.commit()
        markdown = render_digest_markdown(build_daily_digest(db))
        line = next(line for line in markdown.splitlines() if "unverified submission" in line)
        assert line.count("z") == 120
