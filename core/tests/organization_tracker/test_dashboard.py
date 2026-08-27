"""Tests for the server-rendered Organization Tracker dashboard routes
(organization_tracker/dashboard.py) -- mirrors test_dashboard.py's pattern
of hitting real routes through the shared `client` fixture.
"""

from datetime import date

from tests.conftest import make_document

from app.organization_tracker import service


def _setup_position(db):
    ventura = service.create_organization(db, "City of Ventura", "city", date(2020, 1, 1), jurisdiction="City of Ventura")
    position = service.create_position(
        db, title="City Manager", position_type="appointed_executive",
        organization_entity_id=ventura.id, valid_from=date(2015, 1, 1),
    )
    alice = service.create_person(db, "Alice Alvarez")
    service.start_relationship(db, alice.id, "occupies_position", position.id, valid_from=date(2020, 1, 1))
    return ventura, position, alice


class TestOrganizationsListPage:
    def test_renders_with_no_organizations(self, db, client):
        resp = client.get("/organizations")
        assert resp.status_code == 200
        assert "No organizations tracked" in resp.text

    def test_renders_with_an_organization_and_pending_badge(self, db, client):
        ventura, position, alice = _setup_position(db)
        assertion = service.record_assertion(
            db, document_id=make_document(db).id, subject_text="Bob", subject_entity_id=alice.id,
            predicate="occupies_position", object_text="City Manager", object_entity_id=position.id,
            assertion_type="appointment", evidence_mode="explicit", extraction_method="ai_ollama",
        )
        service.propose_event(
            db, organization_entity_id=ventura.id, event_type="appointed", title="x", narrative="x",
            certainty="high", observed_date=date(2026, 1, 1), supporting_assertion_ids=[assertion.id],
        )

        resp = client.get("/organizations")
        assert resp.status_code == 200
        assert "City of Ventura" in resp.text
        assert "pending" in resp.text


class TestOrganizationDetailPage:
    def test_renders_current_structure(self, db, client):
        ventura, position, alice = _setup_position(db)
        resp = client.get(f"/organizations/{ventura.id}")
        assert resp.status_code == 200
        assert "City Manager" in resp.text
        assert "Alice Alvarez" in resp.text

    def test_renders_vacant_when_no_occupant_as_of_that_date(self, db, client):
        # Org and position both exist by 2020-06-01, but Alice's occupancy
        # (set up by _setup_position starting 2020-01-01) hasn't started yet
        # -- need a fixture with a later occupancy start to leave a real gap.
        ventura = service.create_organization(db, "City of Ventura", "city", date(2020, 1, 1))
        position = service.create_position(
            db, title="City Manager", position_type="appointed_executive",
            organization_entity_id=ventura.id, valid_from=date(2020, 1, 1),
        )
        alice = service.create_person(db, "Alice Alvarez")
        service.start_relationship(db, alice.id, "occupies_position", position.id, valid_from=date(2021, 1, 1))

        resp = client.get(f"/organizations/{ventura.id}?at=2020-06-01")
        assert resp.status_code == 200
        assert "vacant" in resp.text


class TestOrganizationReviewPage:
    def test_renders_pending_event_with_evidence(self, db, client):
        ventura, position, alice = _setup_position(db)
        document = make_document(db)
        assertion = service.record_assertion(
            db, document_id=document.id, subject_text="Alice Alvarez", subject_entity_id=alice.id,
            predicate="occupies_position", object_text="City Manager", object_entity_id=position.id,
            assertion_type="appointment", evidence_mode="explicit", extraction_method="ai_ollama",
            quoted_passage="Alice Alvarez, City Manager",
        )
        service.propose_event(
            db, organization_entity_id=ventura.id, event_type="appointed", title="Test event", narrative="x",
            certainty="high", observed_date=date(2026, 1, 1), supporting_assertion_ids=[assertion.id],
            affected_entity_ids=[alice.id],
        )

        resp = client.get(f"/organizations/{ventura.id}/review")
        assert resp.status_code == 200
        assert "Test event" in resp.text
        assert "Alice Alvarez, City Manager" in resp.text
        assert "Approve" in resp.text and "Reject" in resp.text and "Defer" in resp.text

    def test_renders_empty_state(self, db, client):
        ventura, position, alice = _setup_position(db)
        resp = client.get(f"/organizations/{ventura.id}/review")
        assert resp.status_code == 200
        assert "Nothing pending review" in resp.text


class TestReviewEventForm:
    def test_approve_applies_the_relationship_and_redirects(self, db, client):
        ventura = service.create_organization(db, "City of Ventura", "city", date(2020, 1, 1))
        position = service.create_position(
            db, title="City Attorney", position_type="appointed_executive",
            organization_entity_id=ventura.id, valid_from=date(2015, 1, 1),
        )
        carlos = service.create_person(db, "Carlos Cruz")
        assertion = service.record_assertion(
            db, document_id=make_document(db).id, subject_text="Carlos Cruz", subject_entity_id=carlos.id,
            predicate="occupies_position", object_text="City Attorney", object_entity_id=position.id,
            assertion_type="appointment", evidence_mode="explicit", extraction_method="ai_ollama",
        )
        event = service.propose_event(
            db, organization_entity_id=ventura.id, event_type="appointed", title="x", narrative="x",
            certainty="high", observed_date=date(2026, 1, 1), supporting_assertion_ids=[assertion.id],
        )

        resp = client.post(
            f"/organizations/{ventura.id}/events/{event.id}/review",
            data={"decision": "approved", "reviewer_note": "confirmed"},
            follow_redirects=False,
        )
        assert resp.status_code == 303

        from app.organization_tracker.models import OrgRelationship

        rel = db.query(OrgRelationship).filter(OrgRelationship.subject_entity_id == carlos.id).one()
        assert rel.object_entity_id == position.id

    def test_reject_does_not_apply_anything(self, db, client):
        ventura, position, alice = _setup_position(db)
        bob = service.create_person(db, "Bob Baxter")
        assertion = service.record_assertion(
            db, document_id=make_document(db).id, subject_text="Bob Baxter", subject_entity_id=bob.id,
            predicate="occupies_position", object_text="City Manager", object_entity_id=position.id,
            assertion_type="appointment", evidence_mode="explicit", extraction_method="ai_ollama",
        )
        event = service.propose_event(
            db, organization_entity_id=ventura.id, event_type="reassigned", title="x", narrative="x",
            certainty="high", observed_date=date(2026, 1, 1), supporting_assertion_ids=[assertion.id],
        )

        client.post(f"/organizations/{ventura.id}/events/{event.id}/review", data={"decision": "rejected"})

        from app.organization_tracker.models import OrgRelationship

        assert db.query(OrgRelationship).filter(OrgRelationship.subject_entity_id == bob.id).count() == 0
        # Alice's original relationship is untouched.
        assert db.query(OrgRelationship).filter(OrgRelationship.subject_entity_id == alice.id).one().valid_to is None


class TestOrganizationChangesPage:
    def test_shows_reviewed_events_not_pending_ones(self, db, client):
        ventura, position, alice = _setup_position(db)
        bob = service.create_person(db, "Bob Baxter")
        pending_assertion = service.record_assertion(
            db, document_id=make_document(db).id, subject_text="Bob Baxter", subject_entity_id=bob.id,
            predicate="member_of", object_text="City of Ventura", object_entity_id=ventura.id,
            assertion_type="membership", evidence_mode="explicit", extraction_method="ai_ollama",
        )
        pending_event = service.propose_event(
            db, organization_entity_id=ventura.id, event_type="appointed", title="Pending Title", narrative="x",
            certainty="high", observed_date=date(2026, 1, 1), supporting_assertion_ids=[pending_assertion.id],
        )
        reviewed_event = service.propose_event(
            db, organization_entity_id=ventura.id, event_type="appointed", title="Reviewed Title", narrative="x",
            certainty="high", observed_date=date(2026, 1, 1),
        )
        service.review_event(db, reviewed_event.id, "rejected")

        resp = client.get(f"/organizations/{ventura.id}/changes")
        assert resp.status_code == 200
        assert "Reviewed Title" in resp.text
        assert "Pending Title" not in resp.text

    def test_filter_by_review_status(self, db, client):
        ventura, position, alice = _setup_position(db)
        approved_event = service.propose_event(
            db, organization_entity_id=ventura.id, event_type="appointed", title="Approved One", narrative="x",
            certainty="high", observed_date=date(2026, 1, 1),
        )
        service.review_event(db, approved_event.id, "rejected")

        resp = client.get(f"/organizations/{ventura.id}/changes?review_status=approved")
        assert resp.status_code == 200
        assert "Approved One" not in resp.text


class TestEntityDetailPage:
    def test_renders_relationships_and_source_assertions(self, db, client):
        ventura, position, alice = _setup_position(db)
        document = make_document(db)
        service.record_assertion(
            db, document_id=document.id, subject_text="Alice Alvarez", subject_entity_id=alice.id,
            predicate="occupies_position", object_text="City Manager", object_entity_id=position.id,
            assertion_type="appointment", evidence_mode="explicit", extraction_method="ai_ollama",
        )

        resp = client.get(f"/entities/{alice.id}")
        assert resp.status_code == 200
        assert "Alice Alvarez" in resp.text
        assert "City Manager" in resp.text
        assert "occupies_position" in resp.text

    def test_renders_for_a_position_showing_who_holds_it(self, db, client):
        ventura, position, alice = _setup_position(db)
        resp = client.get(f"/entities/{position.id}")
        assert resp.status_code == 200
        assert "Alice Alvarez" in resp.text
