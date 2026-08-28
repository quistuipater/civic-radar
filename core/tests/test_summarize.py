"""Unit tests for summarize_document, closing the gap left by the router
tests (which only exercised the no-Prompt-row 422 path). Unlike classify,
there's no heuristic fallback here -- an Ollama outage just means no
summary this run (recorded as an error, not silently dropped).
"""

import app.ai.summarize as summarize_module

from .conftest import make_document, make_prompt


class TestSummarizeDocument:
    def test_returns_none_when_no_summary_prompt_configured(self, db):
        document = make_document(db, title="Some doc")
        db.commit()

        assert summarize_module.summarize_document(db, document) is None

    def test_returns_none_when_document_has_no_text_at_all(self, db):
        make_prompt(db, prompt_key="document_summary")
        document = make_document(db, title=None, extracted_text_path=None)
        db.commit()

        assert summarize_module.summarize_document(db, document) is None

    def test_uses_model_output_when_ollama_available(self, db, monkeypatch):
        monkeypatch.setattr(summarize_module.ollama_client, "is_available", lambda: True)
        model_output = {"plain_english_summary": "This is what happened.", "source_confidence": "high"}
        monkeypatch.setattr(summarize_module.ollama_client, "generate_json", lambda model, prompt, **k: (model_output, None))
        make_prompt(db, prompt_key="document_summary", model_name="triage-model", prompt_text="{title} {jurisdiction} {text}")
        document = make_document(db, title="June Agenda")
        db.commit()

        output = summarize_module.summarize_document(db, document)

        assert output.output_text == "This is what happened."
        assert output.confidence == "high"
        assert output.model_name == "triage-model"
        assert output.error_message is None

    def test_records_an_error_and_no_summary_when_ollama_unavailable(self, db, monkeypatch):
        monkeypatch.setattr(summarize_module.ollama_client, "is_available", lambda: False)
        make_prompt(db, prompt_key="document_summary")
        document = make_document(db, title="June Agenda")
        db.commit()

        output = summarize_module.summarize_document(db, document)

        assert output is not None
        assert output.output_json is None
        assert output.output_text is None
        assert output.confidence == "none"
        assert output.model_name == "none"
        assert "ollama unavailable" in output.error_message

    def test_records_an_error_when_model_call_fails(self, db, monkeypatch):
        monkeypatch.setattr(summarize_module.ollama_client, "is_available", lambda: True)
        monkeypatch.setattr(
            summarize_module.ollama_client, "generate_json", lambda model, prompt, **k: (None, "model returned invalid JSON")
        )
        make_prompt(db, prompt_key="document_summary", prompt_text="{title} {jurisdiction} {text}")
        document = make_document(db, title="June Agenda")
        db.commit()

        output = summarize_module.summarize_document(db, document)

        assert output.output_json is None
        assert output.model_name == "none"
        assert output.error_message == "model returned invalid JSON"

    def test_prompt_is_formatted_with_document_fields(self, db, monkeypatch):
        seen_prompts = []
        monkeypatch.setattr(summarize_module.ollama_client, "is_available", lambda: True)

        def fake_generate(model, prompt, **k):
            seen_prompts.append(prompt)
            return {"plain_english_summary": "ok"}, None

        monkeypatch.setattr(summarize_module.ollama_client, "generate_json", fake_generate)
        make_prompt(db, prompt_key="document_summary", prompt_text="Title: {title} | Jurisdiction: {jurisdiction}")
        document = make_document(db, title="June Agenda", jurisdiction="City of Ventura")
        db.commit()

        summarize_module.summarize_document(db, document)

        assert seen_prompts[0] == "Title: June Agenda | Jurisdiction: City of Ventura"
