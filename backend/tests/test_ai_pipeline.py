"""Tests for run_ai_pipeline's orchestration/gating logic. The five
sub-steps (embed_document_chunks, extract_agenda_items,
extract_meeting_results, classify_document, summarize_document) are
monkeypatched as spies here -- this module's own job is just deciding
*whether* and *in what order* to call them, which is what these tests
verify, not re-testing each sub-step's internal behavior (already covered
in test_embed.py, test_agenda_items.py, test_meeting_results.py, and the
router tests for classify/summarize).
"""

import app.ai.pipeline as pipeline_module

from .conftest import make_ai_output, make_document


def install_spies(monkeypatch):
    calls = []
    monkeypatch.setattr(pipeline_module, "embed_document_chunks", lambda db, doc: calls.append("embed"))
    monkeypatch.setattr(pipeline_module, "extract_agenda_items", lambda db, doc: calls.append("extract_agenda_items"))
    monkeypatch.setattr(pipeline_module, "extract_meeting_results", lambda db, doc: calls.append("extract_meeting_results"))
    monkeypatch.setattr(pipeline_module, "classify_document", lambda db, doc: calls.append("classify") or object())
    monkeypatch.setattr(pipeline_module, "summarize_document", lambda db, doc: calls.append("summarize"))
    return calls


class TestRunAiPipeline:
    def test_non_classifiable_document_type_is_skipped_entirely(self, db, monkeypatch):
        calls = install_spies(monkeypatch)
        document = make_document(db, document_type="source_page_snapshot", parser_status="parsed")
        db.commit()

        pipeline_module.run_ai_pipeline(db, document)

        assert calls == []

    def test_unparsed_document_is_skipped_entirely(self, db, monkeypatch):
        calls = install_spies(monkeypatch)
        document = make_document(db, document_type="agenda", parser_status="pending")
        db.commit()

        pipeline_module.run_ai_pipeline(db, document)

        assert calls == []

    def test_all_classifiable_types_are_processed(self, db, monkeypatch):
        for doc_type in ("agenda", "minutes", "packet", "notice", "pdf"):
            calls = install_spies(monkeypatch)
            document = make_document(db, document_type=doc_type, parser_status="parsed")
            db.commit()

            pipeline_module.run_ai_pipeline(db, document)

            assert "embed" in calls, doc_type

    def test_embed_extract_agenda_items_and_meeting_results_always_run_before_the_classification_gate(self, db, monkeypatch):
        # These three should run even if the document already has a
        # classification -- only classify/summarize are gated on that.
        calls = install_spies(monkeypatch)
        document = make_document(db, document_type="agenda", parser_status="parsed")
        make_ai_output(db, document.id, task_type="classification")
        db.commit()

        pipeline_module.run_ai_pipeline(db, document)

        assert calls == ["embed", "extract_agenda_items", "extract_meeting_results"]

    def test_classify_and_summarize_run_when_no_prior_classification_exists(self, db, monkeypatch):
        calls = install_spies(monkeypatch)
        document = make_document(db, document_type="agenda", parser_status="parsed")
        db.commit()

        pipeline_module.run_ai_pipeline(db, document)

        assert calls == ["embed", "extract_agenda_items", "extract_meeting_results", "classify", "summarize"]

    def test_a_classification_output_for_a_different_document_does_not_suppress_this_ones(self, db, monkeypatch):
        calls = install_spies(monkeypatch)
        other_document = make_document(db, document_type="agenda", parser_status="parsed")
        make_ai_output(db, other_document.id, task_type="classification")
        document = make_document(db, document_type="agenda", parser_status="parsed")
        db.commit()

        pipeline_module.run_ai_pipeline(db, document)

        assert "classify" in calls

    def test_a_non_classification_output_does_not_suppress_classify_and_summarize(self, db, monkeypatch):
        calls = install_spies(monkeypatch)
        document = make_document(db, document_type="agenda", parser_status="parsed")
        make_ai_output(db, document.id, task_type="summarization")  # not "classification"
        db.commit()

        pipeline_module.run_ai_pipeline(db, document)

        assert "classify" in calls
