"""Seed the source registry (see prd.md section 13.1 for the schema this
follows). Safe to re-run -- existing sources are matched by URL and left
alone rather than duplicated.

FORKED FROM VENTURA CIVIC RADAR, SOURCES NOT YET RESEARCHED FOR BOSTON.
The Ventura instance's SOURCES list held 12 real, individually-verified
sources (city AgendaCenter, county board-of-supervisors and planning-
commission portals, several RMA hearing bodies, two crime-data feeds, two
NetFile campaign-finance/SEI RSS feeds, an elections page, and a Granicus
meeting-audio feed) -- none of those URLs are valid for Boston, so this
list starts empty rather than carrying over facts that would be actively
wrong here. Each entry below sketches the *kind* of source to go find and
verify, mirroring the categories Ventura (and, since, Santa Cruz) ended up
with; delete a bullet once its real source is added, and see README.md's
TODO section for the same list with more context.

Fields (see app/models.py's Source class): name, jurisdiction, agency, body
(None if the source covers multiple bodies), source_type, authority_level
("official_primary" for anything run directly by the government body),
url, fetch_method, connector, polling_interval_minutes, parser_type, and
optionally notes/known_limitations (use known_limitations for anything that
degrades ingestion -- bot walls, empty feeds, schema quirks -- so it's
visible in the dashboard, not just in this file).

TODO -- Boston sources still to find and verify. Note Massachusetts's
municipal/campaign-finance landscape differs structurally from California's
(no county layer the way CA has it for most of these categories -- Boston
is its own city/county consolidated, Suffolk County has essentially no
independent government function relevant here), so don't assume the CA
category boundaries (e.g. "county campaign finance vs. city campaign
finance") translate directly -- verify Massachusetts's actual filing/
disclosure structure (OCPF: Office of Campaign and Political Finance) before
assuming a NetFile-shaped source exists at all:
- City of Boston council/committee agendas (check platform -- Boston uses
  Granicus for its city council per public record as of this repo's fork,
  but verify live rather than trusting that; app/ingestion/meeting_audio.py
  + connectors/civicplus_agenda_center.py + connectors/primegov.py already
  handle the platforms this project has seen elsewhere, but Boston may use
  something else entirely, e.g. Legistar/Granicus Legislative Information
  Center).
- Local crime/police incident data (Boston Police Department publishes a
  well-known open-data "Crime Incident Reports" dataset on Analyze Boston --
  check whether it's ArcGIS FeatureServer-shaped like Ventura's or a
  different open-data platform, e.g. Socrata/CKAN; app/ingestion/
  arcgis_feature_service.py and app/ingestion/crime_data.py's AGENCY_CONFIG
  only handle the ArcGIS shape).
- Campaign finance / disclosure filings -- Massachusetts uses OCPF
  (Office of Campaign and Political Finance), not county-level filing
  officers -- check what platform OCPF publishes on and whether it has an
  RSS/API surface at all before assuming app/ingestion/connectors/
  netfile_rss.py (NetFile-specific) applies.
- Elections office notices/candidate filings (Massachusetts Secretary of
  the Commonwealth / Boston Election Department).
- Meeting audio/video (check whether Boston City Council uses Granicus --
  app/ingestion/meeting_audio.py + whisperx_service/ already handle a
  Granicus podcast RSS feed generically, just needs the real feed URL and a
  WhisperX deployment, see whisperx_service/README.md for what NOT to reuse
  from the existing Ventura deployment).
"""

from app.db import SessionLocal
from app.models import Source

SOURCES: list[dict] = []


def main() -> None:
    db = SessionLocal()
    try:
        created = 0
        for row in SOURCES:
            existing = db.query(Source).filter(Source.url == row["url"]).one_or_none()
            if existing:
                continue
            db.add(Source(**row))
            created += 1
        db.commit()
        print(f"Seeded {created} new source(s); {len(SOURCES) - created} already present.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
