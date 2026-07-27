"""Tests for chunk embedding. ollama_client.is_available()/embed() are
monkeypatched throughout for determinism -- real network calls to whatever
OLLAMA_BASE_URL resolves to have no place in a unit test.
"""

import app.ai.embed as embed_module
from app.models import DocumentChunk

from .conftest import make_document


def add_chunk(db, document, text="chunk text", embedding=None, chunk_index=0):
    chunk = DocumentChunk(document_id=document.id, chunk_index=chunk_index, text=text, embedding=embedding)
    db.add(chunk)
    db.flush()
    return chunk


class TestEmbedDocumentChunks:
    def test_does_nothing_when_ollama_unavailable(self, db, monkeypatch):
        monkeypatch.setattr(embed_module.ollama_client, "is_available", lambda: False)
        document = make_document(db)
        chunk = add_chunk(db, document, embedding=None)
        db.commit()

        embed_module.embed_document_chunks(db, document)

        db.refresh(chunk)
        assert chunk.embedding is None

    def test_embeds_a_chunk_with_no_existing_embedding(self, db, monkeypatch):
        monkeypatch.setattr(embed_module.ollama_client, "is_available", lambda: True)
        monkeypatch.setattr(embed_module.ollama_client, "embed", lambda model, text: ([0.5] * 768, None))
        document = make_document(db)
        chunk = add_chunk(db, document, embedding=None)
        db.commit()

        embed_module.embed_document_chunks(db, document)

        db.refresh(chunk)
        assert chunk.embedding is not None
        assert list(chunk.embedding) == [0.5] * 768

    def test_skips_chunks_that_already_have_an_embedding(self, db, monkeypatch):
        embed_calls = []
        monkeypatch.setattr(embed_module.ollama_client, "is_available", lambda: True)
        monkeypatch.setattr(
            embed_module.ollama_client, "embed", lambda model, text: (embed_calls.append(text) or [0.1] * 768, None)
        )
        document = make_document(db)
        add_chunk(db, document, text="already embedded", embedding=[0.9] * 768, chunk_index=0)
        add_chunk(db, document, text="needs embedding", embedding=None, chunk_index=1)
        db.commit()

        embed_module.embed_document_chunks(db, document)

        assert embed_calls == ["needs embedding"]

    def test_a_failed_embedding_leaves_that_chunk_null_but_does_not_stop_processing_others(self, db, monkeypatch):
        monkeypatch.setattr(embed_module.ollama_client, "is_available", lambda: True)

        def fake_embed(model, text):
            if text == "bad chunk":
                return None, "ollama embedding request failed"
            return [0.3] * 768, None

        monkeypatch.setattr(embed_module.ollama_client, "embed", fake_embed)
        document = make_document(db)
        bad_chunk = add_chunk(db, document, text="bad chunk", embedding=None, chunk_index=0)
        good_chunk = add_chunk(db, document, text="good chunk", embedding=None, chunk_index=1)
        db.commit()

        embed_module.embed_document_chunks(db, document)

        db.refresh(bad_chunk)
        db.refresh(good_chunk)
        assert bad_chunk.embedding is None
        assert good_chunk.embedding is not None

    def test_chunk_text_is_truncated_to_max_chars_before_embedding(self, db, monkeypatch):
        seen_texts = []
        monkeypatch.setattr(embed_module.ollama_client, "is_available", lambda: True)

        def fake_embed(model, text):
            seen_texts.append(text)
            return [0.1] * 768, None

        monkeypatch.setattr(embed_module.ollama_client, "embed", fake_embed)
        document = make_document(db)
        long_text = "x" * (embed_module.MAX_CHARS + 500)
        add_chunk(db, document, text=long_text, embedding=None)
        db.commit()

        embed_module.embed_document_chunks(db, document)

        assert len(seen_texts[0]) == embed_module.MAX_CHARS

    def test_no_chunks_needing_embedding_is_a_no_op(self, db, monkeypatch):
        embed_calls = []
        monkeypatch.setattr(embed_module.ollama_client, "is_available", lambda: True)
        monkeypatch.setattr(embed_module.ollama_client, "embed", lambda model, text: (embed_calls.append(1), None))
        document = make_document(db)
        db.commit()

        embed_module.embed_document_chunks(db, document)

        assert embed_calls == []
