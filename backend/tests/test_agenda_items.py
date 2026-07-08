"""Tests for agenda-item extraction. ollama_client is monkeypatched
throughout for determinism, matching the pattern used for classify/summarize/
embed -- this module has no heuristic fallback at all (structural splitting
isn't something a keyword pass can do reliably), so every path through it
either has a model response or bails out early.
"""

import app.ai.agenda_items as agenda_items_module
from app.models import AgendaItem, AiOutput

from .conftest import make_document, make_meeting, make_prompt


def link_agenda_document(db, meeting, document):
    meeting.agenda_document_id = document.id
    db.flush()


class TestExtractAgendaItems:
    def test_non_agenda_document_types_are_skipped(self, db, monkeypatch):
        called = []
        monkeypatch.setattr(agenda_items_module.ollama_client, "is_available", lambda: called.append(1) or True)
        document = make_document(db, document_type="minutes")
        db.commit()

        agenda_items_module.extract_agenda_items(db, document)

        assert called == []  # never even got as far as checking Ollama

    def test_document_with_no_linked_meeting_is_skipped(self, db, monkeypatch):
        monkeypatch.setattr(agenda_items_module.ollama_client, "is_available", lambda: True)
        document = make_document(db, document_type="agenda")
        db.commit()

        agenda_items_module.extract_agenda_items(db, document)

        assert db.query(AgendaItem).count() == 0

    def test_meeting_with_existing_agenda_items_is_not_reprocessed(self, db, monkeypatch):
        generate_calls = []
        monkeypatch.setattr(agenda_items_module.ollama_client, "is_available", lambda: True)
        monkeypatch.setattr(
            agenda_items_module.ollama_client, "generate_json", lambda *a, **k: generate_calls.append(1) or ({}, None)
        )
        make_prompt(db, prompt_key="agenda_item_extraction")
        meeting = make_meeting(db)
        document = make_document(db, document_type="agenda", extracted_text_path=None, title="has text")
        link_agenda_document(db, meeting, document)
        db.add(AgendaItem(meeting_id=meeting.id, title="Pre-existing item"))
        db.commit()

        agenda_items_module.extract_agenda_items(db, document)

        assert generate_calls == []
        assert db.query(AgendaItem).filter_by(meeting_id=meeting.id).count() == 1

    def test_no_active_prompt_configured_is_skipped(self, db, monkeypatch):
        monkeypatch.setattr(agenda_items_module.ollama_client, "is_available", lambda: True)
        meeting = make_meeting(db)
        document = make_document(db, document_type="agenda")
        link_agenda_document(db, meeting, document)
        db.commit()

        agenda_items_module.extract_agenda_items(db, document)

        assert db.query(AgendaItem).count() == 0
        assert db.query(AiOutput).count() == 0

    def test_ollama_unavailable_is_skipped_even_with_a_prompt_configured(self, db, monkeypatch):
        monkeypatch.setattr(agenda_items_module.ollama_client, "is_available", lambda: False)
        make_prompt(db, prompt_key="agenda_item_extraction")
        meeting = make_meeting(db)
        document = make_document(db, document_type="agenda")
        link_agenda_document(db, meeting, document)
        db.commit()

        agenda_items_module.extract_agenda_items(db, document)

        assert db.query(AgendaItem).count() == 0

    def test_document_with_no_extractable_text_is_skipped(self, db, monkeypatch):
        monkeypatch.setattr(agenda_items_module.ollama_client, "is_available", lambda: True)
        make_prompt(db, prompt_key="agenda_item_extraction")
        meeting = make_meeting(db)
        document = make_document(db, document_type="agenda", title=None, extracted_text_path=None)
        link_agenda_document(db, meeting, document)
        db.commit()

        agenda_items_module.extract_agenda_items(db, document)

        assert db.query(AgendaItem).count() == 0

    def test_successful_extraction_creates_agenda_items_and_records_ai_output(self, db, monkeypatch):
        monkeypatch.setattr(agenda_items_module.ollama_client, "is_available", lambda: True)
        output = {
            "items": [
                {
                    "item_number": "5",
                    "title": "Approve budget amendment",
                    "department": "Finance",
                    "action_type": "action",
                    "consent_calendar": False,
                    "public_hearing": False,
                    "vote_expected": True,
                }
            ]
        }
        monkeypatch.setattr(agenda_items_module.ollama_client, "generate_json", lambda *a, **k: (output, None))
        make_prompt(db, prompt_key="agenda_item_extraction", model_name="triage-model")
        meeting = make_meeting(db)
        document = make_document(db, document_type="agenda", title="June Agenda")
        link_agenda_document(db, meeting, document)
        db.commit()

        agenda_items_module.extract_agenda_items(db, document)

        items = db.query(AgendaItem).filter_by(meeting_id=meeting.id).all()
        assert len(items) == 1
        assert items[0].item_number == "5"
        assert items[0].title == "Approve budget amendment"
        assert items[0].vote_expected is True
        ai_output = db.query(AiOutput).filter_by(task_type="agenda_item_extraction").one()
        assert ai_output.model_name == "triage-model"

    def test_model_failure_records_error_output_and_creates_no_items(self, db, monkeypatch):
        monkeypatch.setattr(agenda_items_module.ollama_client, "is_available", lambda: True)
        monkeypatch.setattr(
            agenda_items_module.ollama_client, "generate_json", lambda *a, **k: (None, "model returned invalid JSON")
        )
        make_prompt(db, prompt_key="agenda_item_extraction")
        meeting = make_meeting(db)
        document = make_document(db, document_type="agenda", title="June Agenda")
        link_agenda_document(db, meeting, document)
        db.commit()

        agenda_items_module.extract_agenda_items(db, document)

        assert db.query(AgendaItem).count() == 0
        ai_output = db.query(AiOutput).filter_by(task_type="agenda_item_extraction").one()
        assert ai_output.error_message == "model returned invalid JSON"
        assert ai_output.model_name == "none"

    def test_output_with_wrong_shape_is_handled_without_crashing(self, db, monkeypatch):
        monkeypatch.setattr(agenda_items_module.ollama_client, "is_available", lambda: True)
        monkeypatch.setattr(agenda_items_module.ollama_client, "generate_json", lambda *a, **k: ({"items": "not-a-list"}, None))
        make_prompt(db, prompt_key="agenda_item_extraction")
        meeting = make_meeting(db)
        document = make_document(db, document_type="agenda", title="June Agenda")
        link_agenda_document(db, meeting, document)
        db.commit()

        agenda_items_module.extract_agenda_items(db, document)

        assert db.query(AgendaItem).count() == 0

    def test_items_missing_a_title_are_skipped(self, db, monkeypatch):
        monkeypatch.setattr(agenda_items_module.ollama_client, "is_available", lambda: True)
        output = {"items": [{"item_number": "1"}, {"title": "Has a title"}]}
        monkeypatch.setattr(agenda_items_module.ollama_client, "generate_json", lambda *a, **k: (output, None))
        make_prompt(db, prompt_key="agenda_item_extraction")
        meeting = make_meeting(db)
        document = make_document(db, document_type="agenda", title="June Agenda")
        link_agenda_document(db, meeting, document)
        db.commit()

        agenda_items_module.extract_agenda_items(db, document)

        items = db.query(AgendaItem).filter_by(meeting_id=meeting.id).all()
        assert len(items) == 1
        assert items[0].title == "Has a title"

    def test_invalid_action_type_is_discarded_rather_than_stored_raw(self, db, monkeypatch):
        monkeypatch.setattr(agenda_items_module.ollama_client, "is_available", lambda: True)
        output = {"items": [{"title": "Some item", "action_type": "not_a_real_action_type"}]}
        monkeypatch.setattr(agenda_items_module.ollama_client, "generate_json", lambda *a, **k: (output, None))
        make_prompt(db, prompt_key="agenda_item_extraction")
        meeting = make_meeting(db)
        document = make_document(db, document_type="agenda", title="June Agenda")
        link_agenda_document(db, meeting, document)
        db.commit()

        agenda_items_module.extract_agenda_items(db, document)

        item = db.query(AgendaItem).filter_by(meeting_id=meeting.id).one()
        assert item.action_type is None

    def test_title_longer_than_2000_chars_is_truncated(self, db, monkeypatch):
        monkeypatch.setattr(agenda_items_module.ollama_client, "is_available", lambda: True)
        output = {"items": [{"title": "x" * 2500}]}
        monkeypatch.setattr(agenda_items_module.ollama_client, "generate_json", lambda *a, **k: (output, None))
        make_prompt(db, prompt_key="agenda_item_extraction")
        meeting = make_meeting(db)
        document = make_document(db, document_type="agenda", title="June Agenda")
        link_agenda_document(db, meeting, document)
        db.commit()

        agenda_items_module.extract_agenda_items(db, document)

        item = db.query(AgendaItem).filter_by(meeting_id=meeting.id).one()
        assert len(item.title) == 2000
