"""Seed the source registry (see prd.md section 13.1 for the schema this
follows). Safe to re-run -- existing sources are matched by URL and left
alone rather than duplicated.

FORKED FROM VENTURA CIVIC RADAR. Source research done 2026-07-10 (live
verification against real endpoints, see README.md's "TODO: Boston source
research" section for the full per-category writeup). Three sources below
needed genuinely new connector code because Boston's real platforms differ
from every one this project has seen in CA (Legistar for council agendas,
OCPF's own REST API for campaign finance) -- crime data was the one clean
"just config" win (Boston PD's dataset is ArcGIS-FeatureServer-shaped, same
as Ventura's). Two categories are still open (see README.md): elections/
candidate-filing notices (boston.gov/public-notices is real and live, but
serves individually-addressable HTML detail pages rather than linked PDFs,
so the generic connector's PDF harvester doesn't apply -- needs its own
bespoke connector, not built yet) and meeting audio (Boston's Granicus
podcast feed is genuinely populated, unlike Santa Cruz's, but the actual
MP3 files are CloudFront-gated and return 403 even with a matching Referer
header -- confirmed, not pursued further, consistent with this project's
standing policy against bypassing access controls).

Fields (see app/models.py's Source class): name, jurisdiction, agency, body
(None if the source covers multiple bodies), source_type, authority_level
("official_primary" for anything run directly by the government body),
url, fetch_method, connector, polling_interval_minutes, parser_type, and
optionally notes/known_limitations (use known_limitations for anything that
degrades ingestion -- bot walls, empty feeds, schema quirks -- so it's
visible in the dashboard, not just in this file).
"""

from app.db import SessionLocal
from app.models import Source

SOURCES: list[dict] = [
    dict(
        name="City of Boston City Council — Legistar",
        jurisdiction="City of Boston",
        agency="City Council",
        body="City Council",
        source_type="agenda_center",
        authority_level="official_primary",
        url="https://webapi.legistar.com/v1/boston/Events?bodyId=138",
        fetch_method="legistar_api",
        connector="none",
        polling_interval_minutes=240,
        parser_type="legistar_api",
        notes=(
            "Legistar (Granicus's legislative management system), not "
            "CivicPlus/PrimeGov (the platforms this project has seen "
            "elsewhere). Confirmed live 2026-07-10: real, documented, "
            "unauthenticated REST/OData API at webapi.legistar.com -- "
            "agenda/minutes PDFs are plain, permanently addressable URLs on "
            "boston.legistar1.com, no session-state dance needed (simpler "
            "than OnBase). BodyId=138 scopes this source to City Council "
            "itself; Legistar also hosts every other Boston body (Zoning "
            "Board of Appeal BodyId=199, School Committee, etc.) on the "
            "same platform -- School Committee is deliberately excluded per "
            "CLAUDE.md's Phase 1 school-board boundary. Handled by "
            "app/ingestion/legistar.py, not the generic connector dispatch "
            "(same reasoning as meeting_audio.py/crime_data.py)."
        ),
    ),
    dict(
        name="Boston Police Department — Crime Incident Reports",
        jurisdiction="City of Boston",
        agency="Boston Police Department",
        body=None,
        source_type="crime_data_feed",
        authority_level="official_primary",
        url="https://services.arcgis.com/sFnw0xNflSi8J0uh/arcgis/rest/services/Boston_Incidents_View/FeatureServer/0",
        fetch_method="arcgis_feature_query",
        connector="none",
        polling_interval_minutes=1440,
        parser_type="arcgis_feature_query",
        notes=(
            "Confirmed live 2026-07-10: genuinely ArcGIS-FeatureServer-"
            "shaped (same platform as Ventura PD's feed), public dataset, "
            "updated once/day with a 7-day lag per its own description. "
            "See app/ingestion/crime_data.py's AGENCY_CONFIG docstring for "
            "why OBJECTID (not the more natural-looking INC_NUM, which "
            "repeats across one incident's multiple offense rows) is the "
            "external_id_field, and why REPORT_DATE was verified as a real "
            "incremental-sync cursor."
        ),
    ),
    dict(
        name="Massachusetts OCPF — Boston Mayor & City Council Filings",
        jurisdiction="City of Boston",
        agency="Office of Campaign and Political Finance",
        body=None,
        source_type="campaign_finance_feed",
        authority_level="official_primary",
        url="https://api.ocpf.us/reports/log",
        fetch_method="json_api_harvest",
        connector="ocpf",
        polling_interval_minutes=240,
        parser_type="ocpf",
        known_limitations=(
            "/reports/log returns only the ~50 most recent filings "
            "statewide, no pagination or date-range params -- if Boston-"
            "relevant filings are ever outpaced by other MA filings between "
            "polls, some could be missed (same class of caveat as NetFile's "
            "rolling-window feeds elsewhere in this project)."
        ),
        notes=(
            "Massachusetts has no county-level filing officers (unlike "
            "every CA fork so far, where NetFile serves that role) -- "
            "campaign-finance disclosure runs through OCPF at the state "
            "level instead. Confirmed live 2026-07-10: real, documented "
            "REST API (Swagger at api.ocpf.us/swagger/v1/swagger.json), "
            "unauthenticated, PDFs at /report/pdf/{reportId}. Scoped via "
            "app/ingestion/connectors/ocpf.py's BOSTON_CPF_IDS allowlist to "
            "the Mayor + 13 City Councilors specifically (from "
            "GET /municipalities' BOSTON entry), not every state "
            "legislator/Sheriff/DA whose district happens to overlap "
            "Boston -- see that module's docstring for why."
        ),
    ),
    dict(
        name="City of Boston Public Notices — Elections",
        jurisdiction="City of Boston",
        agency="Elections Department",
        body=None,
        source_type="notice_board",
        authority_level="official_primary",
        url="https://www.boston.gov/public-notices?field_contact_target_id%5B%5D=551",
        fetch_method="html_pdf_harvest",
        connector="boston_public_notices",
        polling_interval_minutes=1440,
        parser_type="boston_public_notices",
        notes=(
            "Confirmed live 2026-07-10: boston.gov's public-notices board "
            "(Drupal), filtered via its own field_contact_target_id[]=551 "
            "facet to Elections-department notices specifically (the "
            "unfiltered listing spans ~100 city departments, well beyond "
            "this project's scope). Each notice is its own individually-"
            "addressed HTML page, not a linked PDF -- generic.py's PDF "
            "harvester finds nothing here, so this uses a dedicated "
            "connector (app/ingestion/connectors/boston_public_notices.py) "
            "that treats each /public-notices/{id} link on the listing as "
            "the document itself. Low volume by nature (1 live notice as "
            "of first verification) -- that's expected, not a sign of a "
            "broken connector."
        ),
    ),
]


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
