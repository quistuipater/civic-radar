"""Tests for meeting-results extraction. Deliberately has no matching-back-
to-agenda-items logic to test -- see the module docstring for why (item
numbering/formatting drift too much between an agenda and its minutes to
match reliably without a real trial run first). ollama_client is
monkeypatched throughout, same pattern as test_agenda_items.py/test_classify.py.
"""

import app.ai.meeting_results as meeting_results_module
from app.models import AiOutput

from .conftest import make_document, make_prompt


class TestExtractMeetingResults:
    def test_non_minutes_document_types_are_skipped(self, db, monkeypatch):
        called = []
        monkeypatch.setattr(meeting_results_module.ollama_client, "is_available", lambda: called.append(1) or True)
        document = make_document(db, document_type="agenda")
        db.commit()

        result = meeting_results_module.extract_meeting_results(db, document)

        assert result is None
        assert called == []  # never even checked Ollama

    def test_no_active_prompt_configured_is_skipped(self, db, monkeypatch):
        monkeypatch.setattr(meeting_results_module.ollama_client, "is_available", lambda: True)
        document = make_document(db, document_type="minutes", title="June Minutes")
        db.commit()

        result = meeting_results_module.extract_meeting_results(db, document)

        assert result is None
        assert db.query(AiOutput).count() == 0

    def test_ollama_unavailable_is_skipped_even_with_a_prompt_configured(self, db, monkeypatch):
        monkeypatch.setattr(meeting_results_module.ollama_client, "is_available", lambda: False)
        make_prompt(db, prompt_key="meeting_results_summary")
        document = make_document(db, document_type="minutes", title="June Minutes")
        db.commit()

        result = meeting_results_module.extract_meeting_results(db, document)

        assert result is None

    def test_document_with_no_extractable_text_is_skipped(self, db, monkeypatch):
        monkeypatch.setattr(meeting_results_module.ollama_client, "is_available", lambda: True)
        make_prompt(db, prompt_key="meeting_results_summary")
        document = make_document(db, document_type="minutes", title=None, extracted_text_path=None)
        db.commit()

        result = meeting_results_module.extract_meeting_results(db, document)

        assert result is None

    def test_successful_extraction_stores_the_summary_as_an_ai_output(self, db, monkeypatch):
        monkeypatch.setattr(meeting_results_module.ollama_client, "is_available", lambda: True)
        output = {
            "overall_summary": "The council approved the budget amendment 4-1.",
            "key_decisions": [
                {"topic": "Budget amendment", "outcome": "approved", "vote_tally": "4-1", "notes": "Councilmember Lee dissented."}
            ],
            "notable_public_comment": None,
            "continued_or_tabled_items": None,
            "source_confidence": "high",
        }
        monkeypatch.setattr(meeting_results_module.ollama_client, "generate_json", lambda *a, **k: (output, None))
        make_prompt(db, prompt_key="meeting_results_summary", model_name="analysis-model")
        document = make_document(db, document_type="minutes", title="June Minutes")
        db.commit()

        result = meeting_results_module.extract_meeting_results(db, document)

        assert result is not None
        assert result.output_json == output
        assert result.output_text == "The council approved the budget amendment 4-1."
        assert result.confidence == "high"
        assert result.model_name == "analysis-model"
        assert result.task_type == "meeting_results_summary"

    def test_model_failure_records_error_output(self, db, monkeypatch):
        monkeypatch.setattr(meeting_results_module.ollama_client, "is_available", lambda: True)
        monkeypatch.setattr(
            meeting_results_module.ollama_client, "generate_json", lambda *a, **k: (None, "model returned invalid JSON")
        )
        make_prompt(db, prompt_key="meeting_results_summary")
        document = make_document(db, document_type="minutes", title="June Minutes")
        db.commit()

        result = meeting_results_module.extract_meeting_results(db, document)

        assert result is not None
        assert result.output_json is None
        assert result.model_name == "none"
        assert result.confidence == "none"
        assert result.error_message == "model returned invalid JSON"

    def test_rerunning_against_an_already_extracted_document_is_a_no_op(self, db, monkeypatch):
        generate_calls = []
        monkeypatch.setattr(meeting_results_module.ollama_client, "is_available", lambda: True)
        monkeypatch.setattr(
            meeting_results_module.ollama_client,
            "generate_json",
            lambda *a, **k: (generate_calls.append(1) or {"overall_summary": "ok", "key_decisions": [], "source_confidence": "high"}, None),
        )
        make_prompt(db, prompt_key="meeting_results_summary")
        document = make_document(db, document_type="minutes", title="June Minutes")
        db.commit()

        first = meeting_results_module.extract_meeting_results(db, document)
        second = meeting_results_module.extract_meeting_results(db, document)

        assert len(generate_calls) == 1
        assert second.id == first.id
        assert db.query(AiOutput).filter_by(input_ref_id=document.id, task_type="meeting_results_summary").count() == 1

    def test_prompt_is_formatted_with_document_fields(self, db, monkeypatch):
        seen_prompts = []
        monkeypatch.setattr(meeting_results_module.ollama_client, "is_available", lambda: True)

        def fake_generate(model, prompt, timeout=None, **k):
            seen_prompts.append(prompt)
            return {"overall_summary": "ok", "key_decisions": [], "source_confidence": "high"}, None

        monkeypatch.setattr(meeting_results_module.ollama_client, "generate_json", fake_generate)
        make_prompt(db, prompt_key="meeting_results_summary", prompt_text="Jurisdiction: {jurisdiction} | Agency: {agency}")
        document = make_document(db, document_type="minutes", jurisdiction="City of Ventura", agency="City Clerk")
        db.commit()

        meeting_results_module.extract_meeting_results(db, document)

        assert seen_prompts[0] == "Jurisdiction: City of Ventura | Agency: City Clerk"
