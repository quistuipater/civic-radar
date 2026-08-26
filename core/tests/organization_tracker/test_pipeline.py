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
    monkeypatch.setattr(extraction_module.ollama_client, "generate_json", lambda model, prompt: (model_output, None))

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
