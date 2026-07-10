"""Seed the source registry (see prd.md section 13.1 for the schema this
follows). Safe to re-run -- existing sources are matched by URL and left
alone rather than duplicated.

FORKED FROM VENTURA CIVIC RADAR, SOURCES NOT YET RESEARCHED FOR SANTA CRUZ.
The Ventura instance's SOURCES list held 12 real, individually-verified
sources (city AgendaCenter, county board-of-supervisors and planning-
commission portals, several RMA hearing bodies, two crime-data feeds, two
NetFile campaign-finance/SEI RSS feeds, an elections page, and a Granicus
meeting-audio feed) -- none of those URLs are valid for Santa Cruz, so this
list starts empty rather than carrying over facts that would be actively
wrong here. Each entry below sketches the *kind* of source to go find and
verify, mirroring the categories Ventura ended up with; delete a bullet
once its real source is added, and see README.md's TODO section for the
same list with more context.

Fields (see app/models.py's Source class): name, jurisdiction, agency, body
(None if the source covers multiple bodies), source_type, authority_level
("official_primary" for anything run directly by the government body),
url, fetch_method, connector, polling_interval_minutes, parser_type, and
optionally notes/known_limitations (use known_limitations for anything that
degrades ingestion -- bot walls, empty feeds, schema quirks -- so it's
visible in the dashboard, not just in this file).

TODO -- Santa Cruz sources still to find and verify:
- City of Santa Cruz council/commission agendas (check whether the city
  uses CivicPlus AgendaCenter like Ventura did -- app/ingestion/connectors/
  civicplus_agenda_center.py already handles that platform generically --
  or Granicus/Legistar/PrimeGov/something else entirely).
- Santa Cruz County Board of Supervisors meeting agendas/minutes (check for
  a PrimeGov/Legistar/Granicus portal -- app/ingestion/connectors/
  primegov.py already handles PrimeGov's open JSON API generically if that's
  what's in use).
- Santa Cruz County Planning Commission (may be the same portal/platform as
  the Board of Supervisors, as it was for Ventura).
- Local crime/police incident data (check for a public ArcGIS FeatureServer
  like Ventura PD/VC Sheriff had -- app/ingestion/crime_data.py's
  AGENCY_CONFIG and app/ingestion/arcgis_feature_service.py already handle
  that pattern generically, just needs a real agency entry).
- Campaign finance / Statement of Economic Interests filings (check what
  filing platform Santa Cruz County uses -- NetFile, or something else --
  app/ingestion/connectors/netfile_rss.py is NetFile-specific and won't work
  against a different platform without adaptation).
- Elections office notices/candidate filings.
- Meeting audio/video (check whether local bodies use Granicus like Ventura
  -- app/ingestion/meeting_audio.py + whisperx_service/ already handle a
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
