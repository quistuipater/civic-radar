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


def test_three_or_more_identical_assertions_in_one_document_does_not_crash(db):
    """Regression: with 3+ identical assertions, excluding the one being
    classified still leaves 2+ matches -- .one_or_none() raised
    MultipleResultsFound on exactly this input against a real document
    (confirmed live 2026-08-26) before the dedup checks switched to
    .first().
    """
    position, alice = _setup_position(db)
    document = make_document(db)
    for _ in range(3):
        assertion = _assertion(db, alice.id, "occupies_position", position.id, document=document)

    result = reconciliation.classify_assertion(db, assertion)  # the last one created

    assert result.classification == reconciliation.DUPLICATING


def test_duplicating_when_already_proposed_by_a_pending_event_from_a_different_document(db):
    """The real-world case: the same well-known fact (e.g. an incumbent's
    name on every meeting's attendance roster) shows up in document after
    document. Without this check, each one would draft a fresh, near-
    identical "appointed" event -- confirmed live against 25 real Ventura
    documents (43 duplicate drafts) before this check existed.
    """
    position, alice = _setup_position(db)
    first_doc_assertion = _assertion(db, alice.id, "occupies_position", position.id)
    service.propose_event(
        db, organization_entity_id=position.id, event_type="appointed", title="x", narrative="x",
        certainty="high", observed_date=date(2026, 1, 1), supporting_assertion_ids=[first_doc_assertion.id],
    )

    second_doc_assertion = _assertion(db, alice.id, "occupies_position", position.id)

    result = reconciliation.classify_assertion(db, second_doc_assertion)

    assert result.classification == reconciliation.DUPLICATING


def test_not_duplicating_when_the_pending_event_was_already_rejected(db):
    """A rejected proposal doesn't permanently suppress the same claim --
    an operator saying "no" to one document's version of a claim shouldn't
    silently swallow a later, possibly better-evidenced restatement.
    """
    position, alice = _setup_position(db)
    first_doc_assertion = _assertion(db, alice.id, "occupies_position", position.id)
    event = service.propose_event(
        db, organization_entity_id=position.id, event_type="appointed", title="x", narrative="x",
        certainty="high", observed_date=date(2026, 1, 1), supporting_assertion_ids=[first_doc_assertion.id],
    )
    service.review_event(db, event.id, "rejected")

    second_doc_assertion = _assertion(db, alice.id, "occupies_position", position.id)

    result = reconciliation.classify_assertion(db, second_doc_assertion)

    assert result.classification == reconciliation.ADDING
