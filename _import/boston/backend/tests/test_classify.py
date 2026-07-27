"""Unit tests for classify_document/load_document_text, closing the gap
left by the router tests (which only exercised the no-Prompt-row heuristic
fallback, since the test DB has no seeded prompts). These add the actual
model-call path: a configured prompt + available Ollama, and that path
failing and falling back to the heuristic.
"""

import app.ai.classify as classify_module

from .conftest import make_document, make_prompt


class TestClassifyDocument:
    def test_uses_model_output_when_prompt_configured_and_ollama_available(self, db, monkeypatch):
        monkeypatch.setattr(classify_module.ollama_client, "is_available", lambda: True)
        model_output = {"confidence": "high", "importance_score": 7}
        monkeypatch.setattr(classify_module.ollama_client, "generate_json", lambda model, prompt: (model_output, None))
        make_prompt(
            db,
            prompt_key="agenda_item_classification",
            model_name="triage-model",
            prompt_version="v2",
            prompt_text="taxonomy={taxonomy} title={title} jurisdiction={jurisdiction} agency={agency} meeting_date={meeting_date} text={text}",
        )
        document = make_document(db, title="June Agenda")
        db.commit()

        output = classify_module.classify_document(db, document)

        assert output.output_json == model_output
        assert output.model_name == "triage-model"
        assert output.prompt_version == "v2"
        assert output.confidence == "high"
        assert output.error_message is None

    def test_falls_back_to_heuristic_when_model_call_fails(self, db, monkeypatch):
        monkeypatch.setattr(classify_module.ollama_client, "is_available", lambda: True)
        monkeypatch.setattr(
            classify_module.ollama_client, "generate_json", lambda model, prompt: (None, "model returned invalid JSON")
        )
        make_prompt(
            db,
            prompt_key="agenda_item_classification",
            prompt_text="taxonomy={taxonomy} title={title} jurisdiction={jurisdiction} agency={agency} meeting_date={meeting_date} text={text}",
        )
        document = make_document(db, title="An ordinance about coastal development")
        db.commit()

        output = classify_module.classify_document(db, document)

        assert output.model_name == "heuristic"
        assert output.prompt_version == "heuristic-v1"
        assert output.output_json["confidence"] == "low"
        assert output.error_message == "model returned invalid JSON"

    def test_falls_back_to_heuristic_when_ollama_unavailable_even_with_a_prompt_configured(self, db, monkeypatch):
        monkeypatch.setattr(classify_module.ollama_client, "is_available", lambda: False)
        make_prompt(db, prompt_key="agenda_item_classification")
        document = make_document(db, title="Some document")
        db.commit()

        output = classify_module.classify_document(db, document)

        assert output.model_name == "heuristic"

    def test_prompt_is_formatted_with_document_fields(self, db, monkeypatch):
        seen_prompts = []
        monkeypatch.setattr(classify_module.ollama_client, "is_available", lambda: True)

        def fake_generate(model, prompt):
            seen_prompts.append(prompt)
            return {"confidence": "high"}, None

        monkeypatch.setattr(classify_module.ollama_client, "generate_json", fake_generate)
        make_prompt(
            db,
            prompt_key="agenda_item_classification",
            prompt_text="Title: {title} | Agency: {agency}",
        )
        document = make_document(db, title="June Agenda", agency="City Clerk")
        db.commit()

        classify_module.classify_document(db, document)

        assert seen_prompts[0] == "Title: June Agenda | Agency: City Clerk"


class TestLoadDocumentText:
    def test_reads_extracted_text_file_when_present(self, db, tmp_path):
        text_path = tmp_path / "doc.txt"
        text_path.write_text("the real extracted text")
        document = make_document(db, extracted_text_path=str(text_path), title="fallback title")
        db.commit()

        assert classify_module.load_document_text(document) == "the real extracted text"

    def test_falls_back_to_title_when_extracted_text_path_is_unreadable(self, db, tmp_path):
        document = make_document(
            db, extracted_text_path=str(tmp_path / "does-not-exist.txt"), title="fallback title"
        )
        db.commit()

        assert classify_module.load_document_text(document) == "fallback title"

    def test_falls_back_to_empty_string_when_neither_is_available(self, db):
        document = make_document(db, extracted_text_path=None, title=None)
        db.commit()

        assert classify_module.load_document_text(document) == ""
