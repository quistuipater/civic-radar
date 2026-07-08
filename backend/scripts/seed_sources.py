"""Seed the source registry with the Phase 1 sources from prd.md section 13.1.

URLs below were verified live (HTTP 200) against the real sites. Safe to re-run —
existing sources are matched by URL and left alone rather than duplicated.
"""

from app.db import SessionLocal
from app.models import Source

SOURCES = [
    dict(
        name="City of Ventura Agenda Center",
        jurisdiction="City of Ventura",
        agency="City Clerk",
        body=None,  # covers City Council + Planning Commission + other bodies; see connector
        source_type="agenda_center",
        authority_level="official_primary",
        url="https://www.cityofventura.ca.gov/AgendaCenter",
        fetch_method="html_pdf_harvest",
        connector="civicplus_agenda_center",
        polling_interval_minutes=180,
        parser_type="civicplus_agenda_center",
        notes=(
            "CivicPlus AgendaCenter. Single page hosts an accordion of all boards/"
            "committees (City Council, Planning Commission, etc.); each meeting row "
            "links to /AgendaCenter/ViewFile/{Agenda|Minutes}/_MMDDYYYY-<id>, which "
            "serves the PDF directly (verified via HEAD request)."
        ),
    ),
    dict(
        name="Ventura County Board of Supervisors — PrimeGov Portal",
        jurisdiction="Ventura County",
        agency="Board of Supervisors",
        body="Board of Supervisors",
        source_type="meeting_body_page",
        authority_level="official_primary",
        url="https://ventura.primegov.com/public/portal?committee=1",
        fetch_method="html_pdf_harvest",
        connector="primegov",
        polling_interval_minutes=240,
        parser_type="primegov_api",
        notes=(
            "County migrated off Legistar (ventura.legistar.com now returns "
            "'Invalid parameters!' for any request) onto PrimeGov at some point "
            "after this source was first seeded. PrimeGov's portal page is a JS "
            "SPA, but its meeting-list and document-download endpoints are an "
            "open, unauthenticated JSON API (verified live 2026-07-05), so the "
            "primegov connector calls that API directly rather than needing a "
            "headless browser."
        ),
    ),
    dict(
        name="Ventura County Planning Commission — PrimeGov Portal",
        jurisdiction="Ventura County",
        agency="Resource Management Agency",
        body="Planning Commission",
        source_type="meeting_body_page",
        authority_level="official_primary",
        url="https://ventura.primegov.com/public/portal?committee=85",
        fetch_method="html_pdf_harvest",
        connector="primegov",
        polling_interval_minutes=240,
        parser_type="primegov_api",
        notes=(
            "Original URL (rma.venturacounty.gov/divisions/planning/) was a thin "
            "landing page with ~1 real PDF link; real Planning Commission hearing "
            "content is served via the same PrimeGov platform as the Board of "
            "Supervisors (embedded as an iframe on "
            "rma.venturacounty.gov/divisions/planning/planning-commission-hearings-.../, "
            "verified live 2026-07-06), just a different committee id (85 vs 1). "
            "Other RMA bodies (Cultural Heritage Board, Planning Director Hearings, "
            "Mobile Home Park Rent Review Board) are separate sources below, added "
            "the same day as broader RMA coverage."
        ),
    ),
    dict(
        name="Ventura County Cultural Heritage Board — Hearing Notices",
        jurisdiction="Ventura County",
        agency="Resource Management Agency",
        body="Cultural Heritage Board",
        source_type="pdf_directory",
        authority_level="official_primary",
        url="https://rma.venturacounty.gov/divisions/planning/cultural-heritage-board-meetings-and-agendas/",
        fetch_method="html_pdf_harvest",
        connector="generic",
        polling_interval_minutes=240,
        parser_type="generic_pdf_harvest",
        notes=(
            "Real, directly-harvestable hearing-notice PDFs (verified live "
            "2026-07-06, e.g. Piru Citrus Association Labor Camp, Piru Quonset "
            "Hut Community Center notices). Added alongside the Planning "
            "Commission PrimeGov fix as broader RMA coverage."
        ),
    ),
    dict(
        name="Ventura County Planning Director Hearings — Agendas & Staff Reports",
        jurisdiction="Ventura County",
        agency="Resource Management Agency",
        body="Planning Director Hearings",
        source_type="pdf_directory",
        authority_level="official_primary",
        url="https://rma.venturacounty.gov/divisions/planning/planning-director-hearing-agendas/",
        fetch_method="html_pdf_harvest",
        connector="generic",
        polling_interval_minutes=240,
        parser_type="generic_pdf_harvest",
        notes=(
            "Real hearing agendas + staff reports/exhibits (verified live "
            "2026-07-06, e.g. PL24-0111, PL24-0124). Added alongside the "
            "Planning Commission PrimeGov fix as broader RMA coverage."
        ),
    ),
    dict(
        name="Ventura County Mobile Home Park Rent Review Board — Hearing Notices",
        jurisdiction="Ventura County",
        agency="Resource Management Agency",
        body="Mobile Home Park Rent Review Board",
        source_type="pdf_directory",
        authority_level="official_primary",
        url="https://rma.venturacounty.gov/divisions/planning/mobile-home-park-rent-review-board-hearing-notices/",
        fetch_method="html_pdf_harvest",
        connector="generic",
        polling_interval_minutes=1440,
        parser_type="generic_pdf_harvest",
        known_limitations=(
            "No board-specific hearing notices posted as of 2026-07-06 -- page "
            "only has the site-wide boilerplate links (fee schedule, zoning "
            "ordinance), so 0 real documents until this board actually posts "
            "something. Kept as a source anyway per archive-first: nothing "
            "silently missed once it does."
        ),
        notes="County land-use rent-review hearing notices for mobile home parks.",
    ),
    dict(
        name="City of Ventura Police Department — Open Crime Data",
        jurisdiction="City of Ventura",
        agency="Ventura Police Department",
        body=None,
        source_type="crime_data_feed",
        authority_level="official_primary",
        url="https://services.arcgis.com/dBVj4EXO3IdRPOqb/arcgis/rest/services/OpenData_Police_Crimes/FeatureServer/0",
        fetch_method="arcgis_feature_query",
        connector="none",
        polling_interval_minutes=360,
        parser_type="arcgis_feature_service",
        notes=(
            "Real, public, unauthenticated ArcGIS FeatureServer (verified live "
            "2026-07-07) backing the 'Community Crime Map' dashboard at "
            "cityofventura.ca.gov/1052/Community-Crime-Map. Incident-level data "
            "(report number, offense category/type, dates, beat, council "
            "district, community council, block-level address -- addresses are "
            "pre-generalized by the department for privacy). 84k+ total records "
            "as of 2026-07-07. Originally synced incrementally via created_date "
            "as a cursor, but that turned out unreliable two ways (verified live "
            "2026-07-08): every single row shares the *exact same* created_date "
            "value (a bulk-load artifact, not a per-record 'added at' timestamp), "
            "and the field silently fails to filter via `where` at all regardless "
            "-- a `created_date > TIMESTAMP '...'` query returns the unfiltered "
            "full count no matter the threshold, while the identical query "
            "against Incident_Date_Start filters correctly. Falls back to full "
            "re-fetch + dedupe by GlobalID every poll instead (43s per poll at "
            "this size -- fine at 360min intervals). See app/ingestion/"
            "crime_data.py's AGENCY_CONFIG. Structurally different from every "
            "other source: no Document/PDF, just structured rows in the "
            "crime_incidents table. A parallel 'Calls for Service' dashboard "
            "likely has a sibling FeatureServer, not yet traced."
        ),
    ),
    dict(
        name="Ventura County Sheriff's Office — NIBRS Crime Data",
        jurisdiction="Ventura County",
        agency="Ventura County Sheriff's Office",
        body=None,
        source_type="crime_data_feed",
        authority_level="official_primary",
        url="https://services8.arcgis.com/FtD4ZkZ7RhGP9kWV/arcgis/rest/services/NIBRS_Dashboard_2025/FeatureServer/0",
        fetch_method="arcgis_feature_query",
        connector="none",
        polling_interval_minutes=1440,
        parser_type="arcgis_feature_service",
        known_limitations=(
            "Different schema from Ventura PD's feed (verified live "
            "2026-07-08): no GlobalID (uses FID instead), no real incident "
            "date (only an integer Year field), no address/location field at "
            "all -- just Beat/RD/Station. No created_date-equivalent field "
            "either, so this source can't sync incrementally like Ventura PD's "
            "does; every poll re-fetches all ~25k rows and dedupes by FID. "
            "Fine at this scale (daily polling interval); would need revisiting "
            "if the dataset grew towards Ventura PD's ~84k-row scale."
        ),
        notes=(
            "Found via sheriff.venturacounty.gov/transparency-dashboard/"
            "crime-traffic/ -> NIBRS Crime Dashboard (an ArcGIS Experience "
            "Builder app on a separate ArcGIS org from the City of Ventura's). "
            "VC Sheriff also has UCR (1991-2023), Traffic, Hate Crimes, Use of "
            "Force, and RIPA dashboards on the same platform -- not yet added, "
            "underlying FeatureServer URLs not yet traced."
        ),
    ),
    dict(
        name="Ventura County Elections Division",
        jurisdiction="Ventura County",
        agency="Clerk-Recorder / Elections",
        body=None,
        source_type="election_page",
        authority_level="official_primary",
        url="https://clerkrecorder.venturacounty.gov/elections/",
        fetch_method="html_pdf_harvest",
        connector="generic",
        polling_interval_minutes=1440,
        parser_type="generic_pdf_harvest",
        known_limitations=(
            "clerkrecorder.venturacounty.gov sits behind an active AWS WAF bot "
            "challenge (verified live 2026-07-06: plain GET returns HTTP 202 with "
            "empty body and header x-amzn-waf-action: challenge) -- same category "
            "as NetFile's Cloudflare Turnstile. We deliberately don't attempt to "
            "bypass it, so this source stays snapshot-only (generic connector) "
            "until Elections offers a documented public API or bulk-download path."
        ),
        notes="Candidate filings, election calendars, official notices.",
    ),
    dict(
        name="NetFile — Ventura County Campaign Finance Filings (RSS)",
        jurisdiction="Ventura County",
        agency="Elections / Campaign Finance",
        body=None,
        source_type="campaign_filing_feed",
        authority_level="official_primary",
        url="https://netfile.com/connect2/api/public/list/filing/rss/VCO/campaign.xml",
        fetch_method="rss_feed",
        connector="netfile_rss",
        polling_interval_minutes=360,
        parser_type="generic_pdf_harvest",
        notes=(
            "The interactive portal (netfile.com/public/vco/campaign) sits behind "
            "an active Cloudflare Turnstile challenge -- we don't attempt to bypass "
            "it. NetFile separately publishes a real-time, unauthenticated RSS feed "
            "of filings (verified live 2026-07-06: plain HTTP GET, no Turnstile), "
            "with each item linking directly to the filing's PDF. Feed covers only "
            "a rolling window (NetFile's own <description>: max 15 days or 1000 "
            "items), so polling_interval_minutes is set well under that to avoid "
            "gaps -- this is for ongoing monitoring, not historical backfill. "
            "Form 460/470/497/501 etc. for county and city candidates/committees. "
            "See the SEI (Statement of Economic Interests / Form 700) source below "
            "for NetFile's parallel feed. NOT PURSUED (2026-07-07, by request): "
            "there's also a legacy unauthenticated portal at "
            "nf4.netfile.com/pub2/Default.aspx?aid=VCO with zero bot-protection, "
            "full historical Search-by-Date/Name/ID (not limited to the RSS feed's "
            "rolling window), and a year-by-year transaction-level Excel export "
            "(docs/Export_FAQ.txt documents the schema). Would need its own "
            "backfill script (legacy portal) and/or its own data model (Excel "
            "export is transaction-level line items, not documents -- doesn't fit "
            "the Document/PDF pipeline). Worth revisiting if full historical depth "
            "or line-item transaction data becomes a real need."
        ),
    ),
    dict(
        name="NetFile — Ventura County Statement of Economic Interests (RSS)",
        jurisdiction="Ventura County",
        agency="Elections / Campaign Finance",
        body=None,
        source_type="campaign_filing_feed",
        authority_level="official_primary",
        url="https://netfile.com/connect2/api/public/list/filing/rss/VCO/sei.xml",
        fetch_method="rss_feed",
        connector="netfile_rss",
        polling_interval_minutes=360,
        parser_type="generic_pdf_harvest",
        known_limitations=(
            "Feed has had zero items both times checked (2026-07-06, 2026-07-07) -- "
            "real endpoint (same platform/format as the campaign feed, verified "
            "live), just nothing filed in the current rolling window yet. Kept as "
            "a source anyway per archive-first: nothing missed once Form 700s "
            "start showing up."
        ),
        notes=(
            "Form 700 (Statement of Economic Interests) disclosures for elected/"
            "appointed officials -- same RSS platform as the campaign finance feed "
            "above, just the 'sei' feed instead of 'campaign'. Same rolling-window "
            "caveat applies (max 15 days or 1000 items per NetFile's own feed "
            "description)."
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
