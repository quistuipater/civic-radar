from datetime import date

from app.organization_tracker import resolution, service


def test_exact_canonical_name_match_is_case_and_whitespace_insensitive(db):
    person = service.create_person(db, "Jane   Smith")

    resolved = resolution.resolve_entity(db, "  jane smith  ", "person")

    assert resolved is not None
    assert resolved.id == person.id


def test_alias_match(db):
    person = service.create_person(db, "Janet R. Smith", aliases=["Jane Smith"])

    resolved = resolution.resolve_entity(db, "Jane Smith", "person")

    assert resolved is not None
    assert resolved.id == person.id


def test_no_match_returns_none(db):
    service.create_person(db, "Someone Else")

    assert resolution.resolve_entity(db, "Jane Smith", "person") is None


def test_entity_type_scopes_the_match(db):
    ventura = service.create_organization(db, "City of Ventura", "city", date(2020, 1, 1))
    service.create_position(
        db, title="Jane Smith Boulevard Advisory Seat", position_type="appointed",
        organization_entity_id=ventura.id, valid_from=date(2020, 1, 1),
    )

    # A position happens to share a name with a person -- entity_type must
    # keep them from cross-matching.
    assert resolution.resolve_entity(db, "Jane Smith Boulevard Advisory Seat", "person") is None


def test_resolve_entity_id_returns_none_for_empty_text(db):
    assert resolution.resolve_entity_id(db, None, "person") is None
    assert resolution.resolve_entity_id(db, "", "person") is None
