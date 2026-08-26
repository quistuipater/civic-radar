from datetime import date

from tests.conftest import make_document

from app.organization_tracker import event_drafting, service


def _setup_position(db):
    ventura = service.create_organization(db, "City of Ventura", "city", date(2020, 1, 1))
    position = service.create_position(
        db, title="City Manager", position_type="appointed_executive",
        organization_entity_id=ventura.id, valid_from=date(2015, 1, 1),
    )
    alice = service.create_person(db, "Alice Alvarez")
    return ventura, position, alice


def test_no_event_drafted_for_unresolved_assertion(db):
    ventura, position, alice = _setup_position(db)
    document = make_document(db)
    assertion = service.record_assertion(
        db, document_id=document.id, subject_text="Someone", predicate="occupies_position",
        object_text="City Manager", assertion_type="appointment", evidence_mode="explicit",
        extraction_method="ai_ollama",
    )

    assert event_drafting.draft_event_from_assertion(db, assertion, ventura.id) is None


def test_no_event_drafted_when_confirming_existing_state(db):
    ventura, position, alice = _setup_position(db)
    service.start_relationship(db, alice.id, "occupies_position", position.id, valid_from=date(2020, 1, 1))
    document = make_document(db)
    assertion = service.record_assertion(
        db, document_id=document.id, subject_text="Alice Alvarez", subject_entity_id=alice.id,
        predicate="occupies_position", object_text="City Manager", object_entity_id=position.id,
        assertion_type="appointment", evidence_mode="explicit", extraction_method="ai_ollama",
    )

    assert event_drafting.draft_event_from_assertion(db, assertion, ventura.id) is None


def test_explicit_new_appointment_drafts_an_appointed_event(db):
    ventura, position, alice = _setup_position(db)
    document = make_document(db)
    assertion = service.record_assertion(
        db, document_id=document.id, subject_text="Alice Alvarez", subject_entity_id=alice.id,
        predicate="occupies_position", object_text="City Manager", object_entity_id=position.id,
        assertion_type="appointment", evidence_mode="explicit", extraction_method="ai_ollama",
        confidence="high", effective_date=date(2026, 8, 1), quoted_passage="Alice Alvarez was appointed City Manager.",
    )

    event = event_drafting.draft_event_from_assertion(db, assertion, ventura.id)

    assert event is not None
    assert event.event_type == "appointed"
    assert event.certainty == "high"
    assert event.effective_date == date(2026, 8, 1)
    assert event.review_status == "pending"
    assert "Alice Alvarez was appointed City Manager." in event.narrative


def test_contradicting_occupancy_drafts_a_reassigned_event(db):
    ventura, position, alice = _setup_position(db)
    service.start_relationship(db, alice.id, "occupies_position", position.id, valid_from=date(2018, 1, 1))
    bob = service.create_person(db, "Bob Baxter")
    document = make_document(db)
    assertion = service.record_assertion(
        db, document_id=document.id, subject_text="Bob Baxter", subject_entity_id=bob.id,
        predicate="occupies_position", object_text="City Manager", object_entity_id=position.id,
        assertion_type="appointment", evidence_mode="explicit", extraction_method="ai_ollama",
    )

    event = event_drafting.draft_event_from_assertion(db, assertion, ventura.id)

    assert event is not None
    assert event.event_type == "reassigned"
    assert "supersedes a previously accepted" in event.narrative


def test_non_explicit_evidence_drafts_unexplained_state_change_not_a_specific_action(db):
    """The whole point: derived/inferred evidence never becomes a claimed
    "appointed"/"resigned"/etc. event -- that would be exactly the kind of
    unsupported personnel-action inference the project's guardrails forbid.
    """
    ventura, position, alice = _setup_position(db)
    document = make_document(db)
    assertion = service.record_assertion(
        db, document_id=document.id, subject_text="Alice Alvarez", subject_entity_id=alice.id,
        predicate="occupies_position", object_text="City Manager", object_entity_id=position.id,
        assertion_type="appointment", evidence_mode="inferred", extraction_method="ai_ollama",
    )

    event = event_drafting.draft_event_from_assertion(db, assertion, ventura.id)

    assert event is not None
    assert event.event_type == "unexplained_state_change"
    assert "does not explicitly state the underlying event" in event.narrative
