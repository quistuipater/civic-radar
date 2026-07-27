"""Router test for /api/search. The semantic-search half calls
ollama_client.embed() directly with no gate on whether a Prompt row exists
(unlike classify/summarize), so it's explicitly monkeypatched here rather
than left to depend on whatever settings.ollama_base_url happens to resolve
to in a given environment -- that would make this test's pass/fail depend
on real network state, which is exactly what a unit test shouldn't do.
"""

import app.routers.search as search_module
from app.models import DocumentChunk

from .conftest import make_document, make_issue


class TestSearch:
    def test_keyword_match_on_document_title(self, db, client, monkeypatch):
        monkeypatch.setattr(search_module.ollama_client, "embed", lambda model, text: (None, "unavailable"))
        make_document(db, title="Downtown Parking Ordinance")
        make_document(db, title="Unrelated Notice")
        db.commit()

        resp = client.get("/api/search", params={"q": "Parking"})

        assert resp.status_code == 200
        titles = [d["title"] for d in resp.json()["documents"]]
        assert titles == ["Downtown Parking Ordinance"]

    def test_keyword_match_on_project_number(self, db, client, monkeypatch):
        monkeypatch.setattr(search_module.ollama_client, "embed", lambda model, text: (None, "unavailable"))
        make_document(db, title="Some Agenda", project_number="PL26-0042")
        db.commit()

        resp = client.get("/api/search", params={"q": "PL26-0042"})

        assert len(resp.json()["documents"]) == 1

    def test_matches_issues_by_title_and_summary(self, db, client, monkeypatch):
        monkeypatch.setattr(search_module.ollama_client, "embed", lambda model, text: (None, "unavailable"))
        make_issue(db, title="Downtown Parking Ordinance", summary="about parking")
        make_issue(db, title="Unrelated Issue", summary="about something else")
        db.commit()

        resp = client.get("/api/search", params={"q": "Parking"})

        titles = [i["title"] for i in resp.json()["issues"]]
        assert titles == ["Downtown Parking Ordinance"]

    def test_semantic_matches_is_empty_list_when_ollama_unavailable(self, db, client, monkeypatch):
        monkeypatch.setattr(search_module.ollama_client, "embed", lambda model, text: (None, "connection refused"))
        make_document(db, title="Some Document")
        db.commit()

        resp = client.get("/api/search", params={"q": "anything"})

        assert resp.status_code == 200
        assert resp.json()["semantic_matches"] == []

    def test_semantic_matches_are_returned_when_embedding_is_available(self, db, client, monkeypatch):
        document = make_document(db, title="Document With A Chunk")
        chunk = DocumentChunk(
            document_id=document.id,
            chunk_index=0,
            page_start=1,
            page_end=1,
            text="some chunk text " * 30,
            embedding=[0.1] * 768,
        )
        db.add(chunk)
        db.commit()

        monkeypatch.setattr(search_module.ollama_client, "embed", lambda model, text: ([0.1] * 768, None))

        resp = client.get("/api/search", params={"q": "some chunk text"})

        assert resp.status_code == 200
        matches = resp.json()["semantic_matches"]
        assert len(matches) == 1
        assert matches[0]["document_id"] == str(document.id)
        assert matches[0]["chunk_id"] == str(chunk.id)
        assert matches[0]["distance"] < 0.01  # identical vector -> ~0 cosine distance
        assert len(matches[0]["snippet"]) <= 400

    def test_semantic_matches_excludes_chunks_with_no_embedding(self, db, client, monkeypatch):
        document = make_document(db)
        chunk = DocumentChunk(
            document_id=document.id, chunk_index=0, text="unembedded chunk", embedding=None
        )
        db.add(chunk)
        db.commit()

        monkeypatch.setattr(search_module.ollama_client, "embed", lambda model, text: ([0.1] * 768, None))

        resp = client.get("/api/search", params={"q": "anything"})

        assert resp.json()["semantic_matches"] == []

    def test_no_matches_anywhere_returns_empty_lists_not_an_error(self, client, monkeypatch):
        monkeypatch.setattr(search_module.ollama_client, "embed", lambda model, text: (None, "unavailable"))

        resp = client.get("/api/search", params={"q": "nothing matches this"})

        assert resp.status_code == 200
        assert resp.json() == {"documents": [], "issues": [], "semantic_matches": []}
