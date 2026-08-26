from datetime import date

from tests.conftest import make_document, make_prompt

from app.organization_tracker import extraction, service
from app.organization_tracker import extraction as extraction_module


def _prompt(db):
    return make_prompt(
        db, prompt_key="org_assertion_extraction", task_type="org_assertion_extraction",
        prompt_text="{project_name} {document_type} {jurisdiction} {agency} {text}",
    )


def test_no_assertions_created_without_a_configured_prompt(db, monkeypatch):
    monkeypatch.setattr(extraction_module.ollama_client, "is_available", lambda: True)
    document = make_document(db, extracted_text_path=None)

    result = extraction.extract_assertions_from_document(db, document)

    assert result == []


def test_no_assertions_created_when_ollama_unavailable(db, monkeypatch):
    _prompt(db)
    monkeypatch.setattr(extraction_module.ollama_client, "is_available", lambda: False)
    document = make_document(db)

    assert extraction.extract_assertions_from_document(db, document) == []


def test_creates_assertions_from_model_output_and_resolves_known_entities(db, monkeypatch, tmp_path):
    _prompt(db)
    monkeypatch.setattr(extraction_module.ollama_client, "is_available", lambda: True)

    text_path = tmp_path / "doc.txt"
    text_path.write_text("Jane Smith was appointed City Manager effective 2026-08-01.")
    document = make_document(db, extracted_text_path=str(text_path))

    ventura = service.create_organization(db, "City of Ventura", "city", date(2020, 1, 1))
    position = service.create_position(
        db, title="City Manager", position_type="appointed_executive",
        organization_entity_id=ventura.id, valid_from=date(2015, 1, 1),
    )

    model_output = {
        "assertions": [
            {
                "subject_text": "Jane Smith",
                "predicate": "occupies_position",
                "object_text": "City Manager",
                "assertion_type": "appointment",
                "effective_date": "2026-08-01",
                "evidence_mode": "explicit",
                "quoted_passage": "Jane Smith was appointed City Manager effective 2026-08-01.",
                "confidence": "high",
            }
        ]
    }
    monkeypatch.setattr(extraction_module.ollama_client, "generate_json", lambda model, prompt: (model_output, None))

    created = extraction.extract_assertions_from_document(db, document)

    assert len(created) == 1
    assertion = created[0]
    assert assertion.subject_text == "Jane Smith"
    assert assertion.subject_entity_id is None  # "Jane Smith" -- no matching person entity exists yet
    assert assertion.object_entity_id == position.id  # "City Manager" resolves to the real position
    assert assertion.effective_date == date(2026, 8, 1)
    assert assertion.evidence_mode == "explicit"
    assert assertion.extraction_method == "ai_ollama"
    assert assertion.model_name == "test-model"


def test_incomplete_model_rows_are_skipped_not_guessed(db, monkeypatch):
    _prompt(db)
    monkeypatch.setattr(extraction_module.ollama_client, "is_available", lambda: True)
    document = make_document(db)

    model_output = {"assertions": [{"subject_text": "Jane Smith"}]}  # missing predicate/evidence_mode/type
    monkeypatch.setattr(extraction_module.ollama_client, "generate_json", lambda model, prompt: (model_output, None))

    assert extraction.extract_assertions_from_document(db, document) == []


def test_model_error_yields_no_assertions_not_a_crash(db, monkeypatch):
    _prompt(db)
    monkeypatch.setattr(extraction_module.ollama_client, "is_available", lambda: True)
    document = make_document(db)
    monkeypatch.setattr(
        extraction_module.ollama_client, "generate_json", lambda model, prompt: (None, "model returned invalid JSON")
    )

    assert extraction.extract_assertions_from_document(db, document) == []
