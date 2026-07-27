"""Tests for alert generation from a document's AI classification output.
Covers trigger-reason assembly, deadline-field priority, title fallback,
and the dedup_key uniqueness guarantee that makes re-running the pipeline
against an already-classified document a safe no-op.
"""

from datetime import date

from app.alerting import create_alert_from_classification
from app.models import Alert, Issue

from .conftest import make_ai_output, make_document, make_source


def classification(**overrides) -> dict:
    defaults = dict(
        importance_score=1,
        urgency_score=1,
        transparency_risk_score=1,
        hearing_expected=False,
        vote_expected=False,
        public_participation_opportunity=False,
        rationale="test rationale",
    )
    defaults.update(overrides)
    return defaults


class TestCreateAlertFromClassification:
    def test_creates_an_alert_with_the_computed_level_and_dedup_key(self, db):
        document = make_document(db)
        output = make_ai_output(db, document.id, output_json=classification(importance_score=8, urgency_score=8))

        alert = create_alert_from_classification(db, document, output)

        assert alert is not None
        assert alert.alert_level == 4
        assert alert.dedup_key == f"document:{document.id}:4"
        assert alert.document_id == document.id

    def test_missing_score_fields_default_to_zero_rather_than_crashing(self, db):
        document = make_document(db)
        output = make_ai_output(db, document.id, output_json={})

        alert = create_alert_from_classification(db, document, output)

        assert alert is not None
        assert alert.alert_level == 1

    def test_no_trigger_bits_falls_back_to_routine_classification(self, db):
        document = make_document(db)
        output = make_ai_output(db, document.id, output_json=classification())

        alert = create_alert_from_classification(db, document, output)

        assert alert.trigger_reason == "routine classification"

    def test_multiple_trigger_bits_are_joined_with_semicolons(self, db):
        document = make_document(db)
        output = make_ai_output(
            db,
            document.id,
            output_json=classification(
                hearing_expected=True, vote_expected=True, transparency_risk_score=6
            ),
        )

        alert = create_alert_from_classification(db, document, output)

        assert alert.trigger_reason == "hearing expected; vote expected; elevated transparency risk"

    def test_public_participation_opportunity_is_its_own_trigger_bit(self, db):
        document = make_document(db)
        output = make_ai_output(db, document.id, output_json=classification(public_participation_opportunity=True))

        alert = create_alert_from_classification(db, document, output)

        assert alert.trigger_reason == "public comment opportunity"

    def test_comment_deadline_takes_priority_over_other_dates(self, db):
        document = make_document(
            db,
            comment_deadline=date(2026, 1, 1),
            public_hearing_date=date(2026, 2, 1),
            meeting_date=date(2026, 3, 1),
        )
        output = make_ai_output(db, document.id, output_json=classification())

        alert = create_alert_from_classification(db, document, output)

        assert alert.deadline.date() == date(2026, 1, 1)

    def test_public_hearing_date_used_when_no_comment_deadline(self, db):
        document = make_document(db, public_hearing_date=date(2026, 2, 1), meeting_date=date(2026, 3, 1))
        output = make_ai_output(db, document.id, output_json=classification())

        alert = create_alert_from_classification(db, document, output)

        assert alert.deadline.date() == date(2026, 2, 1)

    def test_meeting_date_used_as_last_resort(self, db):
        document = make_document(db, meeting_date=date(2026, 3, 1))
        output = make_ai_output(db, document.id, output_json=classification())

        alert = create_alert_from_classification(db, document, output)

        assert alert.deadline.date() == date(2026, 3, 1)

    def test_deadline_is_none_when_no_dates_are_set(self, db):
        document = make_document(db)
        output = make_ai_output(db, document.id, output_json=classification())

        alert = create_alert_from_classification(db, document, output)

        assert alert.deadline is None

    def test_uses_document_title_when_present(self, db):
        document = make_document(db, title="June Agenda")
        output = make_ai_output(db, document.id, output_json=classification())

        alert = create_alert_from_classification(db, document, output)

        assert alert.title == "June Agenda"

    def test_falls_back_to_generated_title_when_document_has_none(self, db):
        source = make_source(db)
        document = make_document(db, source=source, title=None, document_type="notice", body="Planning Commission")
        output = make_ai_output(db, document.id, output_json=classification())

        alert = create_alert_from_classification(db, document, output)

        assert alert.title == "New notice — Planning Commission"

    def test_issue_id_is_set_when_an_issue_is_passed(self, db):
        document = make_document(db)
        output = make_ai_output(db, document.id, output_json=classification())
        issue = Issue(title="Test Issue", slug="test-issue", status="open")
        db.add(issue)
        db.flush()

        alert = create_alert_from_classification(db, document, output, issue=issue)

        assert alert.issue_id == issue.id

    def test_issue_id_is_none_when_no_issue_is_passed(self, db):
        document = make_document(db)
        output = make_ai_output(db, document.id, output_json=classification())

        alert = create_alert_from_classification(db, document, output)

        assert alert.issue_id is None

    def test_rerunning_against_an_already_alerted_document_and_level_is_a_no_op(self, db):
        document = make_document(db)
        output = make_ai_output(db, document.id, output_json=classification(importance_score=8, urgency_score=8))

        first = create_alert_from_classification(db, document, output)
        second = create_alert_from_classification(db, document, output)

        assert first is not None
        assert second is None
        assert db.query(Alert).filter_by(document_id=document.id).count() == 1
