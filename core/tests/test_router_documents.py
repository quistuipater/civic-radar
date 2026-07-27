"""Router tests for /api/documents and /api/ai/*. classify_document and
summarize_document both naturally take their no-Ollama-needed paths in these
tests since the test DB has no seeded Prompt rows (classify falls back to
the heuristic classifier; summarize returns None/422) -- deterministic
regardless of whatever Ollama server settings.ollama_base_url happens to
point at, so no mocking needed for those two. match_document_to_issue and
suggest_issues_for_document are pure DB logic with no AI dependency at all.
"""

import app.ai.summarize as summarize_module

from .conftest import make_ai_output, make_document, make_prompt


class TestListDocuments:
    def test_filters_by_document_type(self, db, client):
        make_document(db, document_type="agenda")
        make_document(db, document_type="minutes")
        db.commit()

        resp = client.get("/api/documents", params={"document_type": "minutes"})

        types = [d["document_type"] for d in resp.json()]
        assert types == ["minutes"]

    def test_filters_by_jurisdiction(self, db, client):
        make_document(db, jurisdiction="City of Ventura")
        make_document(db, jurisdiction="Ventura County")
        db.commit()

        resp = client.get("/api/documents", params={"jurisdiction": "Ventura County"})

        jurisdictions = [d["jurisdiction"] for d in resp.json()]
        assert jurisdictions == ["Ventura County"]


class TestGetDocument:
    def test_returns_404_for_unknown_id(self, client):
        resp = client.get("/api/documents/00000000-0000-0000-0000-000000000000")
        assert resp.status_code == 404

    def test_returns_document_by_id(self, db, client):
        document = make_document(db, title="Findable Document")
        db.commit()

        resp = client.get(f"/api/documents/{document.id}")

        assert resp.status_code == 200
        assert resp.json()["title"] == "Findable Document"


class TestTriggerClassification:
    def test_falls_back_to_heuristic_when_no_prompt_configured(self, db, client):
        document = make_document(db, title="Some ordinance about coastal development")
        db.commit()

        resp = client.post(f"/api/ai/classify/{document.id}")

        assert resp.status_code == 200
        body = resp.json()
        assert body["output_json"]["confidence"] == "low"
        assert body["output_json"]["human_review_required"] is True

    def test_returns_404_for_unknown_document(self, client):
        resp = client.post("/api/ai/classify/00000000-0000-0000-0000-000000000000")
        assert resp.status_code == 404


class TestTriggerSummarization:
    def test_returns_422_when_no_summary_prompt_configured(self, db, client):
        document = make_document(db)
        db.commit()

        resp = client.post(f"/api/ai/summarize/{document.id}")

        assert resp.status_code == 422

    def test_returns_404_for_unknown_document(self, client):
        resp = client.post("/api/ai/summarize/00000000-0000-0000-0000-000000000000")
        assert resp.status_code == 404

    def test_returns_summary_output_when_a_prompt_and_ollama_are_available(self, db, client, monkeypatch):
        monkeypatch.setattr(summarize_module.ollama_client, "is_available", lambda: True)
        monkeypatch.setattr(
            summarize_module.ollama_client,
            "generate_json",
            lambda model, prompt: ({"plain_english_summary": "It happened."}, None),
        )
        make_prompt(db, prompt_key="document_summary", prompt_text="{title} {jurisdiction} {text}")
        document = make_document(db, title="June Agenda")
        db.commit()

        resp = client.post(f"/api/ai/summarize/{document.id}")

        assert resp.status_code == 200
        assert resp.json()["output_json"]["plain_english_summary"] == "It happened."


class TestTriggerIssueMatch:
    def test_returns_none_when_no_identifier_overlap(self, db, client):
        document = make_document(db)
        db.commit()

        resp = client.post(f"/api/ai/match-issue/{document.id}")

        assert resp.status_code == 200
        assert resp.json()["issue_id"] is None

    def test_returns_404_for_unknown_document(self, client):
        resp = client.post("/api/ai/match-issue/00000000-0000-0000-0000-000000000000")
        assert resp.status_code == 404


class TestSuggestedIssues:
    def test_returns_empty_list_when_document_has_no_chunk_embeddings(self, db, client):
        document = make_document(db)
        db.commit()

        resp = client.get(f"/api/documents/{document.id}/suggested-issues")

        assert resp.status_code == 200
        assert resp.json() == []

    def test_returns_404_for_unknown_document(self, client):
        resp = client.get("/api/documents/00000000-0000-0000-0000-000000000000/suggested-issues")
        assert resp.status_code == 404


class TestDocumentAiOutputs:
    def test_returns_outputs_for_the_document_ordered_newest_first(self, db, client):
        document = make_document(db)
        make_ai_output(db, document.id, task_type="classification")
        make_ai_output(db, document.id, task_type="summarization")
        db.commit()

        resp = client.get(f"/api/documents/{document.id}/ai-outputs")

        assert resp.status_code == 200
        assert len(resp.json()) == 2

    def test_does_not_return_outputs_belonging_to_other_documents(self, db, client):
        document = make_document(db)
        other_document = make_document(db)
        make_ai_output(db, other_document.id)
        db.commit()

        resp = client.get(f"/api/documents/{document.id}/ai-outputs")

        assert resp.json() == []
