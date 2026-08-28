"""Extends Organization Tracker's Ventura baseline (organization_baseline.py)
with the City's operating departments -- Council/Mayor/City Manager/City
Attorney/City Clerk are already seeded there; this adds the department-level
units and their current directors, which the PRD's org-structure goal also
covers but the first baseline pass didn't reach (see organization_tracker's
README, "Explicitly deferred -- Ventura source configuration" section,
which flagged units as unpopulated).

Every department and director name here was verified live 2026-08-27
against the City's own site: the department list comes from
cityofventura.ca.gov/27/Government (the real nav, not the site's
JS-rendered /directory.aspx summary page, which was cross-checked and
found to list a stale director for Community Development -- Rachel Dimond
-- when the department's own page states Maruja Clensay was named interim
director effective 2026-08-27, the day this was seeded). Each director name
below was confirmed either directly on that department's own city page, or
via a live web search cross-referencing at least one independent news
source (Ventura Breeze / PublicCEO / Ojai Valley News) alongside the city
site, matching the rigor organization_baseline.py used for the council.
Meredith Hart / Economic Development Manager also independently
cross-confirms against extraction.py's real test document (see
organization_tracker/README.md's roster mis-pairing note) --
the same name/title pair recovered correctly there.

valid_from is TODAY (2026-08-27), the observation date, not a claimed
appointment date -- same reasoning as organization_baseline.py: city pages
rarely give a reliable effective date, and Community Development's interim
appointment is the only one here with a stated effective date that happens
to also be today.

Safe to re-run: each unit is preceded by a resolution.resolve_entity check.
"""

from datetime import date

from app.db import SessionLocal
from app.organization_tracker import resolution, service

TODAY = date(2026, 8, 27)

# (unit name, unit_type, director name, director title)
# Source: individual department pages linked from cityofventura.ca.gov/27/Government,
# fetched live 2026-08-27; police/fire/public-works/water director names
# cross-confirmed via independent news coverage (see module docstring).
DEPARTMENTS = [
    ("Finance", "department", "Greg Morley", "Chief Financial Officer"),
    ("Human Resources", "department", "Valerie Barroso", "Director of Human Resources"),
    ("Information Technology", "department", "Mike Shaffer", "Chief Technology Officer"),
    ("Community Development", "department", "Maruja Clensay", "Interim Community Development Director"),
    ("Fire Department", "department", "Kris McDonald", "Fire Chief"),
    ("Parks & Recreation", "department", "Stacey Zarazua", "Parks & Recreation Director"),
    ("Police Department", "department", "David Dickey", "Chief of Police"),
    ("Public Works", "department", "Charlie Ebeling", "Public Works Director"),
    ("Ventura Water", "department", "Gina Dorrington", "Ventura Water General Manager"),
    ("Economic Development", "division", "Meredith Hart", "Economic Development Manager"),
]


def main() -> None:
    db = SessionLocal()
    try:
        ventura = resolution.resolve_entity(db, "City of Ventura", "organization")
        if ventura is None:
            print("City of Ventura organization not seeded yet; run organization_baseline.py first.")
            return

        created = 0
        for unit_name, unit_type, director_name, director_title in DEPARTMENTS:
            existing_unit = resolution.resolve_entity(db, unit_name, "organizational_unit")
            if existing_unit is not None:
                print(f"{unit_name} already seeded; skipping.")
                continue

            unit = service.create_unit(
                db, canonical_name=unit_name, unit_type=unit_type,
                organization_entity_id=ventura.id, valid_from=TODAY,
            )
            position = service.create_position(
                db, title=director_title, position_type="appointed_executive",
                organization_entity_id=ventura.id, unit_entity_id=unit.id, valid_from=TODAY,
            )
            person = resolution.resolve_entity(db, director_name, "person")
            if person is None:
                person = service.create_person(db, director_name)
            service.start_relationship(db, person.id, "occupies_position", position.id, valid_from=TODAY)
            created += 1

        print(f"Seeded {created} department unit(s) with director(s).")
    finally:
        db.close()


if __name__ == "__main__":
    main()
