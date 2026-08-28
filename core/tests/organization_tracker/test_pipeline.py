from datetime import date

from tests.conftest import make_document, make_prompt

from app.organization_tracker import pipeline, service
from app.organization_tracker import extraction as extraction_module


def test_process_document_extracts_and_drafts_events(db, monkeypatch, tmp_path):
    make_prompt(
        db, prompt_key="org_assertion_extraction", task_type="org_assertion_extraction",
        prompt_text="{project_name} {document_type} {jurisdiction} {agency} {text}",
    )
    monkeypatch.setattr(extraction_module.ollama_client, "is_available", lambda: True)

    text_path = tmp_path / "doc.txt"
    text_path.write_text("Alice Alvarez was appointed City Manager.")
    document = make_document(db, extracted_text_path=str(text_path))

    ventura = service.create_organization(db, "City of Ventura", "city", date(2020, 1, 1))
    position = service.create_position(
        db, title="City Manager", position_type="appointed_executive",
        organization_entity_id=ventura.id, valid_from=date(2015, 1, 1),
    )
    service.create_person(db, "Alice Alvarez")

    model_output = {
        "assertions": [
            {
                "subject_text": "Alice Alvarez", "predicate": "occupies_position", "object_text": "City Manager",
                "assertion_type": "appointment", "effective_date": None, "evidence_mode": "explicit",
                "quoted_passage": "Alice Alvarez was appointed City Manager.", "confidence": "high",
            }
        ]
    }
    monkeypatch.setattr(extraction_module.ollama_client, "generate_json", lambda model, prompt, **k: (model_output, None))

    result = pipeline.process_document_for_organization(db, document, ventura.id)

    assert len(result.assertions) == 1
    assert result.assertions[0].object_entity_id == position.id
    assert len(result.drafted_events) == 1
    assert result.drafted_events[0].event_type == "appointed"
    assert result.drafted_events[0].review_status == "pending"


def test_process_document_with_no_extracted_assertions_drafts_nothing(db, monkeypatch):
    make_prompt(db, prompt_key="org_assertion_extraction", task_type="org_assertion_extraction", prompt_text="{text}")
    monkeypatch.setattr(extraction_module.ollama_client, "is_available", lambda: False)
    document = make_document(db)
    ventura = service.create_organization(db, "City of Ventura", "city", date(2020, 1, 1))

    result = pipeline.process_document_for_organization(db, document, ventura.id)

    assert result.assertions == []
    assert result.drafted_events == []


class TestRunBatch:
    def test_no_op_when_no_organizations_are_tracked(self, db, monkeypatch):
        # No service.create_organization call at all -- simulates Santa
        # Cruz/Boston, which have no Organization Tracker seed data.
        make_document(db, parser_status="parsed")
        monkeypatch.setattr(extraction_module.ollama_client, "is_available", lambda: True)

        pipeline.run_batch(db)

        from app.organization_tracker.models import OrgDocumentProcessing

        assert db.query(OrgDocumentProcessing).count() == 0

    def test_document_processed_and_marked_even_with_zero_assertions(self, db, monkeypatch):
        make_prompt(
            db, prompt_key="org_assertion_extraction", task_type="org_assertion_extraction", prompt_text="{text}"
        )
        monkeypatch.setattr(extraction_module.ollama_client, "is_available", lambda: False)  # forces zero assertions
        ventura = service.create_organization(
            db, "City of Ventura", "city", date(2020, 1, 1), jurisdiction="City of Ventura"
        )
        document = make_document(db, parser_status="parsed", jurisdiction="City of Ventura")

        pipeline.run_batch(db)

        from app.organization_tracker.models import OrgDocumentProcessing

        row = db.query(OrgDocumentProcessing).filter(OrgDocumentProcessing.document_id == document.id).one()
        assert row.organizations_matched == 1
        assert row.assertions_created == 0
        assert row.events_drafted == 0

    def test_document_not_reprocessed_on_a_second_run(self, db, monkeypatch):
        make_prompt(
            db, prompt_key="org_assertion_extraction", task_type="org_assertion_extraction", prompt_text="{text}"
        )
        monkeypatch.setattr(extraction_module.ollama_client, "is_available", lambda: False)
        service.create_organization(db, "City of Ventura", "city", date(2020, 1, 1), jurisdiction="City of Ventura")
        make_document(db, parser_status="parsed", jurisdiction="City of Ventura")

        pipeline.run_batch(db)
        pipeline.run_batch(db)

        from app.organization_tracker.models import OrgDocumentProcessing

        assert db.query(OrgDocumentProcessing).count() == 1

    def test_jurisdiction_mismatch_is_processed_but_matches_no_organization(self, db, monkeypatch):
        make_prompt(
            db, prompt_key="org_assertion_extraction", task_type="org_assertion_extraction", prompt_text="{text}"
        )
        monkeypatch.setattr(extraction_module.ollama_client, "is_available", lambda: False)
        service.create_organization(db, "City of Ventura", "city", date(2020, 1, 1), jurisdiction="City of Ventura")
        document = make_document(db, parser_status="parsed", jurisdiction="Santa Cruz County")

        pipeline.run_batch(db)

        from app.organization_tracker.models import OrgDocumentProcessing

        row = db.query(OrgDocumentProcessing).filter(OrgDocumentProcessing.document_id == document.id).one()
        assert row.organizations_matched == 0

    def test_only_parsed_documents_are_considered(self, db, monkeypatch):
        make_prompt(
            db, prompt_key="org_assertion_extraction", task_type="org_assertion_extraction", prompt_text="{text}"
        )
        monkeypatch.setattr(extraction_module.ollama_client, "is_available", lambda: False)
        service.create_organization(db, "City of Ventura", "city", date(2020, 1, 1), jurisdiction="City of Ventura")
        make_document(db, parser_status="pending", jurisdiction="City of Ventura")

        pipeline.run_batch(db)

        from app.organization_tracker.models import OrgDocumentProcessing

        assert db.query(OrgDocumentProcessing).count() == 0
