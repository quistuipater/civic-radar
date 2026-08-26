from datetime import date

from tests.conftest import make_document

from app.organization_tracker import reconciliation, service


def _setup_position(db):
    ventura = service.create_organization(db, "City of Ventura", "city", date(2020, 1, 1))
    position = service.create_position(
        db, title="City Manager", position_type="appointed_executive",
        organization_entity_id=ventura.id, valid_from=date(2015, 1, 1),
    )
    alice = service.create_person(db, "Alice Alvarez")
    return position, alice


def _assertion(db, subject_id, predicate, object_id, document=None):
    document = document or make_document(db)
    return service.record_assertion(
        db, document_id=document.id, subject_text="x", subject_entity_id=subject_id,
        predicate=predicate, object_text="y", object_entity_id=object_id,
        assertion_type="appointment", evidence_mode="explicit", extraction_method="ai_ollama",
    )


def test_unresolved_when_entities_not_resolved(db):
    document = make_document(db)
    assertion = service.record_assertion(
        db, document_id=document.id, subject_text="Someone", predicate="occupies_position",
        object_text="Some Position", assertion_type="appointment", evidence_mode="explicit",
        extraction_method="ai_ollama",
    )

    result = reconciliation.classify_assertion(db, assertion)

    assert result.classification == reconciliation.UNRESOLVED


def test_adding_when_no_relationship_exists_yet(db):
    position, alice = _setup_position(db)
    assertion = _assertion(db, alice.id, "occupies_position", position.id)

    result = reconciliation.classify_assertion(db, assertion)

    assert result.classification == reconciliation.ADDING


def test_confirming_when_assertion_matches_open_relationship(db):
    position, alice = _setup_position(db)
    service.start_relationship(db, alice.id, "occupies_position", position.id, valid_from=date(2020, 1, 1))
    assertion = _assertion(db, alice.id, "occupies_position", position.id)

    result = reconciliation.classify_assertion(db, assertion)

    assert result.classification == reconciliation.CONFIRMING
    assert result.conflicting_relationship_id is not None


def test_contradicting_when_assertion_names_a_different_object(db):
    position, alice = _setup_position(db)
    service.start_relationship(db, alice.id, "occupies_position", position.id, valid_from=date(2020, 1, 1))
    other_position, _ = _setup_position(db)
    # alice asserted to occupy a *different* position while still open on the first
    assertion = _assertion(db, alice.id, "occupies_position", other_position.id)

    result = reconciliation.classify_assertion(db, assertion)

    assert result.classification == reconciliation.CONTRADICTING


def test_duplicating_when_identical_assertion_already_exists_for_same_document(db):
    position, alice = _setup_position(db)
    document = make_document(db)
    first = _assertion(db, alice.id, "occupies_position", position.id, document=document)

    second = service.record_assertion(
        db, document_id=document.id, subject_text="x", subject_entity_id=alice.id,
        predicate="occupies_position", object_text="y", object_entity_id=position.id,
        assertion_type="appointment", evidence_mode="explicit", extraction_method="ai_ollama",
    )

    result = reconciliation.classify_assertion(db, second)

    assert result.classification == reconciliation.DUPLICATING
    assert first.id != second.id
