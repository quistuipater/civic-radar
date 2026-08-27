"""Seeds Organization Tracker's reviewed baseline model of the City of
Ventura (PRD "MVP goals": "create a reviewed baseline model of the City of
Ventura"). This is baseline data an operator is asserting as already-known
and correct -- not AI-extracted content awaiting review -- so it goes
straight through service.py's create/start_relationship functions rather
than the assertion/reconciliation/event-drafting pipeline extraction.py
etc. use for ongoing documents.

Every name and title here was verified live 2026-08-27 against two
independent sources: the City's own official staff-directory pages
(cityofventura.ca.gov/directory.aspx, one per person, fetched directly --
council term dates shown on those pages were inconsistent/stale, so are
NOT used here) and real archived Ventura City Council meeting minutes
already in this project's own document archive (which is how the City
Manager/City Attorney/City Clerk names were cross-confirmed). Nothing
here is guessed or inferred.

valid_from for every relationship below is 2026-08-27 (today, the
observation date), not a claimed appointment/election date -- the city's
own directory pages showed stale/inconsistent term-start dates, and
recording an unverified date as if it were the real effective date would
violate the PRD's own bitemporal principle ("an ingestion date must not
silently become an effective date"). This baseline states "known to hold
this position as of today," nothing more specific.

Safe to re-run: every create_* call is preceded by a resolution.resolve_entity
check so re-running doesn't create duplicate entities. Does NOT re-check or
recreate relationships if the organization already exists, on the
assumption that once seeded, ongoing changes flow through the real
extraction/reconciliation/event-drafting pipeline instead.
"""

from datetime import date

from app.db import SessionLocal
from app.organization_tracker import resolution, service

TODAY = date(2026, 8, 27)

# (display_name, title, district) -- source: cityofventura.ca.gov/directory.aspx
# EID=459,395,515,409,460,461,516 respectively, fetched live 2026-08-27.
COUNCIL_ROSTER = [
    ("Liz Campos", "Councilmember", 1),
    ("Doug Halter", "Councilmember", 2),
    ("Ryyn Schumacher", "Councilmember", 3),
    ("Dr. Jeannette Sánchez-Palacios", "Councilmember", 4),
    ("Bill McReynolds", "Councilmember", 5),
    ("Jim Duran", "Councilmember", 6),
    ("Alex Mangone", "Councilmember", 7),
]
# Mayor/Deputy Mayor are annually-selected titles held *in addition to* a
# district seat (see cityofventura.ca.gov/733/Selection-of-Mayor), not
# separate elected seats -- modeled as their own rotating Position entities.
MAYOR = "Dr. Jeannette Sánchez-Palacios"
DEPUTY_MAYOR = "Doug Halter"

# Source: real archived City Council minutes (e.g. the 2026-08-18 meeting),
# cross-confirmed against the roster attendance line each time.
APPOINTED_OFFICIALS = [
    ("Bill Ayub", "City Manager", "appointed_executive"),
    ("Javan N. Rad", "City Attorney", "appointed_executive"),
    ("Michael B. MacDonald", "City Clerk", "appointed_executive"),
]


def main() -> None:
    db = SessionLocal()
    try:
        ventura = resolution.resolve_entity(db, "City of Ventura", "organization")
        if ventura is not None:
            print("City of Ventura organization already seeded; skipping.")
            return

        ventura = service.create_organization(
            db, "City of Ventura", "city", TODAY, jurisdiction="City of Ventura"
        )

        council_seats: dict[str, object] = {}
        for name, title, district in COUNCIL_ROSTER:
            seat = service.create_position(
                db, title=f"{title} — District {district}", position_type="elected",
                organization_entity_id=ventura.id, valid_from=TODAY,
            )
            council_seats[name] = seat
            person = service.create_person(db, name)
            service.start_relationship(db, person.id, "occupies_position", seat.id, valid_from=TODAY)

        mayor_position = service.create_position(
            db, title="Mayor", position_type="elected_title", organization_entity_id=ventura.id, valid_from=TODAY
        )
        deputy_mayor_position = service.create_position(
            db, title="Deputy Mayor", position_type="elected_title",
            organization_entity_id=ventura.id, valid_from=TODAY,
        )
        mayor_person = resolution.resolve_entity(db, MAYOR, "person")
        deputy_mayor_person = resolution.resolve_entity(db, DEPUTY_MAYOR, "person")
        service.start_relationship(db, mayor_person.id, "occupies_position", mayor_position.id, valid_from=TODAY)
        service.start_relationship(
            db, deputy_mayor_person.id, "occupies_position", deputy_mayor_position.id, valid_from=TODAY
        )

        for name, title, position_type in APPOINTED_OFFICIALS:
            position = service.create_position(
                db, title=title, position_type=position_type, organization_entity_id=ventura.id, valid_from=TODAY
            )
            person = service.create_person(db, name)
            service.start_relationship(db, person.id, "occupies_position", position.id, valid_from=TODAY)

        print(
            f"Seeded City of Ventura baseline: 1 organization, "
            f"{len(COUNCIL_ROSTER) + 2 + len(APPOINTED_OFFICIALS)} positions, "
            f"{len(COUNCIL_ROSTER) + len(APPOINTED_OFFICIALS)} people."
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
