"""Extends the Ventura Organization Tracker baseline with reporting/
appointment relationships, so the dashboard can answer "who reports to
whom" and "how does the Council relate to the rest of the org" -- not just
"who currently holds this position" (organization_baseline.py and
organization_departments_baseline.py). Run after both of those.

Two relationship types, both directly sourced from the City's own
"Form of Government" page (cityofventura.ca.gov/287/Form-of-Government),
fetched live 2026-08-27:

1. "The City Council hires 2 of the principal officials of the City, the
   City Manager and the City Attorney" -- modeled as a real "City Council"
   organizational_unit entity (distinct from the 7 individual district-seat
   Positions, which is how the council baseline already models each
   member's seat) with an "appoints" relationship to both positions.
   The City Clerk is deliberately NOT included here -- the source page
   names only "2" principal officials hired by Council, and no page found
   during research stated the Clerk's appointing authority, so asserting a
   third would be a guess this project's discipline doesn't allow.

2. "[The City Manager is] the administrative head of the City government
   responsible to the City Council for the administration of all City
   affairs" including "hiring and firing department heads" -- modeled as
   each of the 10 department-head Positions seeded in
   organization_departments_baseline.py having a "reports_to_position"
   relationship to the City Manager position.

valid_from is TODAY (2026-08-27), the observation date, matching the same
reasoning as the other two baseline scripts (source pages describe current
authority, not a specific effective date).

Safe to re-run: the City Council unit is checked via resolution before
creating; the appoints/reports_to_position relationships are checked by
querying for an existing open relationship with the same subject/predicate/
object before inserting.
"""

from datetime import date

from app.db import SessionLocal
from app.organization_tracker import resolution, service
from app.organization_tracker.models import OrgRelationship

TODAY = date(2026, 8, 27)

DEPARTMENT_DIRECTOR_TITLES = [
    "Chief Financial Officer",
    "Director of Human Resources",
    "Chief Technology Officer",
    "Interim Community Development Director",
    "Fire Chief",
    "Parks & Recreation Director",
    "Chief of Police",
    "Public Works Director",
    "Ventura Water General Manager",
    "Economic Development Manager",
]


def _relationship_exists(db, subject_id, predicate, object_id) -> bool:
    return (
        db.query(OrgRelationship)
        .filter(
            OrgRelationship.subject_entity_id == subject_id,
            OrgRelationship.relationship_type == predicate,
            OrgRelationship.object_entity_id == object_id,
            OrgRelationship.valid_to.is_(None),
        )
        .first()
        is not None
    )


def main() -> None:
    db = SessionLocal()
    try:
        ventura = resolution.resolve_entity(db, "City of Ventura", "organization")
        if ventura is None:
            print("City of Ventura organization not seeded yet; run organization_baseline.py first.")
            return

        city_manager = resolution.resolve_entity(db, "City Manager", "position")
        city_attorney = resolution.resolve_entity(db, "City Attorney", "position")
        if city_manager is None or city_attorney is None:
            print("City Manager/City Attorney positions not seeded yet; run organization_baseline.py first.")
            return

        council = resolution.resolve_entity(db, "City Council", "organizational_unit")
        if council is None:
            council = service.create_unit(
                db, canonical_name="City Council", unit_type="legislative_body",
                organization_entity_id=ventura.id, valid_from=TODAY,
            )
            print("Created City Council unit.")

        created = 0
        for target in (city_manager, city_attorney):
            if not _relationship_exists(db, council.id, "appoints", target.id):
                service.start_relationship(db, council.id, "appoints", target.id, valid_from=TODAY)
                created += 1

        for title in DEPARTMENT_DIRECTOR_TITLES:
            director_position = resolution.resolve_entity(db, title, "position")
            if director_position is None:
                print(f"Position '{title}' not found; run organization_departments_baseline.py first. Skipping.")
                continue
            if not _relationship_exists(db, director_position.id, "reports_to_position", city_manager.id):
                service.start_relationship(
                    db, director_position.id, "reports_to_position", city_manager.id, valid_from=TODAY
                )
                created += 1

        print(f"Seeded {created} reporting/appointment relationship(s).")
    finally:
        db.close()


if __name__ == "__main__":
    main()
