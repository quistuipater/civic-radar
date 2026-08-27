"""Covers the acceptance criteria this PR's scope actually implements:
temporal versioning (positions/units), point-in-time occupancy, assertion
correction history, and the event review lifecycle. Entity resolution,
AI extraction, and automatic reconciliation are explicitly out of scope
for this pass -- see organization_tracker/README.md.
"""

from datetime import date

from app.organization_tracker import service
from tests.conftest import make_document


def _make_ventura(db):
    return service.create_organization(
        db, canonical_name="City of Ventura", org_type="city", valid_from=date(2020, 1, 1),
        jurisdiction="Ventura County",
    )


def test_unit_rename_preserves_history_and_is_queryable_at_a_date(db):
    ventura = _make_ventura(db)
    unit = service.create_unit(
        db, canonical_name="Community Development Department", unit_type="department",
        organization_entity_id=ventura.id, valid_from=date(2022, 1, 1),
    )

    service.rename_or_transfer_unit(
        db, unit_entity_id=unit.id, as_of=date(2024, 6, 1),
        canonical_name="Community Development & Sustainability Department",
    )

    from app.organization_tracker.models import UnitVersion

    versions = (
        db.query(UnitVersion).filter(UnitVersion.entity_id == unit.id).order_by(UnitVersion.valid_from).all()
    )
    assert len(versions) == 2
    assert versions[0].canonical_name == "Community Development Department"
    assert versions[0].valid_to == date(2024, 6, 1)
    assert versions[1].canonical_name == "Community Development & Sustainability Department"
    assert versions[1].valid_to is None

    # Old name was still correct before the rename -- history isn't rewritten.
    as_of_before = (
        db.query(UnitVersion)
        .filter(UnitVersion.entity_id == unit.id, UnitVersion.valid_from <= date(2023, 1, 1))
        .filter((UnitVersion.valid_to.is_(None)) | (UnitVersion.valid_to > date(2023, 1, 1)))
        .one()
    )
    assert as_of_before.canonical_name == "Community Development Department"


def test_position_occupancy_transition_is_point_in_time_correct(db):
    ventura = _make_ventura(db)
    position = service.create_position(
        db, title="City Manager", position_type="appointed_executive",
        organization_entity_id=ventura.id, valid_from=date(2015, 1, 1),
    )
    alice = service.create_person(db, "Alice Alvarez")
    bob = service.create_person(db, "Bob Baxter")

    service.start_relationship(db, alice.id, "occupies_position", position.id, valid_from=date(2018, 3, 1))

    # Transition to Bob on 2024-01-01: close Alice's occupancy, open Bob's.
    from app.organization_tracker.models import OrgRelationship

    open_rel = (
        db.query(OrgRelationship)
        .filter(OrgRelationship.subject_entity_id == alice.id, OrgRelationship.object_entity_id == position.id)
        .filter(OrgRelationship.valid_to.is_(None))
        .one()
    )
    service.end_relationship(db, open_rel.id, valid_to=date(2024, 1, 1))
    service.start_relationship(db, bob.id, "occupies_position", position.id, valid_from=date(2024, 1, 1))

    def occupant_at(as_of):
        return (
            db.query(OrgRelationship)
            .filter(OrgRelationship.object_entity_id == position.id, OrgRelationship.relationship_type == "occupies_position")
            .filter(OrgRelationship.valid_from <= as_of)
            .filter((OrgRelationship.valid_to.is_(None)) | (OrgRelationship.valid_to > as_of))
            .one()
            .subject_entity_id
        )

    assert occupant_at(date(2020, 1, 1)) == alice.id
    assert occupant_at(date(2024, 6, 1)) == bob.id


def test_replace_relationship_closes_old_and_opens_new_for_the_same_subject(db):
    """replace_relationship's intended case: one person moving from one
    position to another (a reassignment), not succession -- succession
    (different people, same position) is the close/open pair used above.
    """
    ventura = _make_ventura(db)
    deputy = service.create_position(
        db, title="Deputy City Manager", position_type="appointed_executive",
        organization_entity_id=ventura.id, valid_from=date(2015, 1, 1),
    )
    manager = service.create_position(
        db, title="City Manager", position_type="appointed_executive",
        organization_entity_id=ventura.id, valid_from=date(2015, 1, 1),
    )
    dana = service.create_person(db, "Dana Diaz")
    service.start_relationship(db, dana.id, "occupies_position", deputy.id, valid_from=date(2020, 1, 1))

    service.replace_relationship(
        db, subject_entity_id=dana.id, relationship_type="occupies_position",
        old_object_entity_id=deputy.id, new_object_entity_id=manager.id, as_of=date(2026, 3, 1),
    )

    from app.organization_tracker.models import OrgRelationship

    deputy_rel = (
        db.query(OrgRelationship)
        .filter(OrgRelationship.subject_entity_id == dana.id, OrgRelationship.object_entity_id == deputy.id)
        .one()
    )
    manager_rel = (
        db.query(OrgRelationship)
        .filter(OrgRelationship.subject_entity_id == dana.id, OrgRelationship.object_entity_id == manager.id)
        .one()
    )
    assert deputy_rel.valid_to == date(2026, 3, 1)
    assert manager_rel.valid_from == date(2026, 3, 1)
    assert manager_rel.valid_to is None


def test_assertion_correction_creates_superseding_row_not_a_mutation(db):
    source = make_document(db)
    original = service.record_assertion(
        db, document_id=source.id, subject_text="Jane Smith", predicate="appointed_as",
        object_text="Interim City Manager", assertion_type="appointment",
        evidence_mode="explicit", extraction_method="human_manual_entry",
    )

    corrected = service.record_assertion(
        db, document_id=source.id, subject_text="Jane Smith", predicate="appointed_as",
        object_text="Permanent City Manager", assertion_type="appointment",
        evidence_mode="explicit", extraction_method="human_manual_entry",
        superseded_assertion_id=original.id,
    )

    db.refresh(original)
    assert original.review_status == "superseded"
    assert corrected.superseded_assertion_id == original.id
    # The original row still exists with its original claim -- not deleted or rewritten.
    assert original.object_text == "Interim City Manager"


def test_event_review_lifecycle_preserves_history(db):
    ventura = _make_ventura(db)
    position = service.create_position(
        db, title="Public Works Director", position_type="appointed_executive",
        organization_entity_id=ventura.id, valid_from=date(2015, 1, 1),
    )
    assertion = service.record_assertion(
        db, document_id=make_document(db).id, subject_text="Carlos Cruz", predicate="appointed_as",
        object_text="Public Works Director", assertion_type="appointment",
        evidence_mode="explicit", extraction_method="human_manual_entry",
    )

    event = service.propose_event(
        db, organization_entity_id=ventura.id, event_type="appointed", title="Carlos Cruz appointed Public Works Director",
        narrative="Council agenda item confirms appointment effective 2026-08-01.",
        certainty="high", observed_date=date(2026, 8, 4), effective_date=date(2026, 8, 1),
        supporting_assertion_ids=[assertion.id], affected_entity_ids=[position.id],
    )
    assert event.review_status == "pending"

    reviewed = service.review_event(db, event.id, "approved", reviewer_note="Confirmed against agenda item 12.")
    assert reviewed.review_status == "approved"
    assert reviewed.reviewer_note == "Confirmed against agenda item 12."
    assert reviewed.reviewed_at is not None

    from app.organization_tracker.models import OrgEventAssertion, OrgEventEntity

    assert db.query(OrgEventAssertion).filter(OrgEventAssertion.event_id == event.id).count() == 1
    assert db.query(OrgEventEntity).filter(OrgEventEntity.event_id == event.id).count() == 1


def test_approving_an_appointed_event_applies_the_relationship(db):
    """The PRD's "Acceptance is transactional": approving isn't just a
    label change, it applies the underlying relationship -- otherwise
    the org chart never actually updates from a reviewed event.
    """
    ventura = _make_ventura(db)
    position = service.create_position(
        db, title="Public Works Director", position_type="appointed_executive",
        organization_entity_id=ventura.id, valid_from=date(2015, 1, 1),
    )
    carlos = service.create_person(db, "Carlos Cruz")
    assertion = service.record_assertion(
        db, document_id=make_document(db).id, subject_text="Carlos Cruz", subject_entity_id=carlos.id,
        predicate="occupies_position", object_text="Public Works Director", object_entity_id=position.id,
        assertion_type="appointment", evidence_mode="explicit", extraction_method="human_manual_entry",
    )
    event = service.propose_event(
        db, organization_entity_id=ventura.id, event_type="appointed", title="x", narrative="x",
        certainty="high", observed_date=date(2026, 8, 4), effective_date=date(2026, 8, 1),
        supporting_assertion_ids=[assertion.id],
    )

    from app.organization_tracker.models import OrgRelationship

    assert db.query(OrgRelationship).count() == 0  # nothing accepted yet, still pending

    service.review_event(db, event.id, "approved")

    rel = db.query(OrgRelationship).filter(
        OrgRelationship.subject_entity_id == carlos.id, OrgRelationship.object_entity_id == position.id
    ).one()
    assert rel.valid_from == date(2026, 8, 1)  # the assertion's own effective_date, not observed_date
    assert rel.valid_to is None


def test_approving_a_reassigned_event_closes_the_prior_occupant(db):
    ventura = _make_ventura(db)
    position = service.create_position(
        db, title="City Manager", position_type="appointed_executive",
        organization_entity_id=ventura.id, valid_from=date(2015, 1, 1),
    )
    alice = service.create_person(db, "Alice Alvarez")
    bob = service.create_person(db, "Bob Baxter")
    service.start_relationship(db, alice.id, "occupies_position", position.id, valid_from=date(2018, 1, 1))

    assertion = service.record_assertion(
        db, document_id=make_document(db).id, subject_text="Bob Baxter", subject_entity_id=bob.id,
        predicate="occupies_position", object_text="City Manager", object_entity_id=position.id,
        assertion_type="appointment", evidence_mode="explicit", extraction_method="human_manual_entry",
    )
    event = service.propose_event(
        db, organization_entity_id=ventura.id, event_type="reassigned", title="x", narrative="x",
        certainty="high", observed_date=date(2026, 8, 4), effective_date=date(2026, 8, 1),
        supporting_assertion_ids=[assertion.id],
    )

    service.review_event(db, event.id, "approved")

    from app.organization_tracker.models import OrgRelationship

    alice_rel = db.query(OrgRelationship).filter(OrgRelationship.subject_entity_id == alice.id).one()
    bob_rel = db.query(OrgRelationship).filter(OrgRelationship.subject_entity_id == bob.id).one()
    assert alice_rel.valid_to == date(2026, 8, 1)
    assert bob_rel.valid_to is None


def test_approving_an_unexplained_state_change_applies_nothing(db):
    ventura = _make_ventura(db)
    position = service.create_position(
        db, title="City Manager", position_type="appointed_executive",
        organization_entity_id=ventura.id, valid_from=date(2015, 1, 1),
    )
    someone = service.create_person(db, "Someone Unclear")
    assertion = service.record_assertion(
        db, document_id=make_document(db).id, subject_text="Someone Unclear", subject_entity_id=someone.id,
        predicate="occupies_position", object_text="City Manager", object_entity_id=position.id,
        assertion_type="appointment", evidence_mode="inferred", extraction_method="ai_ollama",
    )
    event = service.propose_event(
        db, organization_entity_id=ventura.id, event_type="unexplained_state_change", title="x", narrative="x",
        certainty="low", observed_date=date(2026, 8, 4), supporting_assertion_ids=[assertion.id],
    )

    service.review_event(db, event.id, "approved")

    from app.organization_tracker.models import OrgRelationship

    assert db.query(OrgRelationship).count() == 0


def test_review_event_rejects_invalid_decision(db):
    ventura = _make_ventura(db)
    event = service.propose_event(
        db, organization_entity_id=ventura.id, event_type="renamed", title="x", narrative="x",
        certainty="low", observed_date=date(2026, 1, 1),
    )
    import pytest

    with pytest.raises(ValueError):
        service.review_event(db, event.id, "maybe")
