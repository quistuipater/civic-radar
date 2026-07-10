"""Seed the source registry (see prd.md section 13.1 for the schema this
follows). Safe to re-run -- existing sources are matched by URL and left
alone rather than duplicated.

FORKED FROM VENTURA CIVIC RADAR. Source research done 2026-07-10 (live
verification against real endpoints, see README.md's "TODO: Santa Cruz
source research" section for the full per-category writeup). Six sources
use connectors that already existed (PrimeGov, NetFile, generic) -- no new
code needed. The City of Santa Cruz agenda source below needed a dedicated
connector (app/ingestion/onbase_agenda.py, OnBase's 2-step download flow)
which is now built. County Planning Commission (legacy ASP frameset) and
crime data (not found) are still open -- see README.md for status.
"""

from app.db import SessionLocal
from app.models import Source

SOURCES: list[dict] = [
    dict(
        name="City of Santa Cruz Agenda Online — OnBase",
        jurisdiction="City of Santa Cruz",
        agency="City Clerk",
        body=None,  # covers City Council + every board/committee; see connector
        source_type="agenda_center",
        authority_level="official_primary",
        url="https://ecm.cityofsantacruz.com/OnBaseAgendaOnline/",
        fetch_method="onbase_agenda_online",
        connector="none",
        polling_interval_minutes=240,
        parser_type="onbase_agenda_online",
        notes=(
            "Hyland OnBase, not CivicPlus (Ventura's platform). Confirmed live "
            "2026-07-10: single page lists every board/committee's meetings, "
            "each row carrying a real meeting id + Unix timestamp + body name. "
            "Document downloads need a 2-step POST-then-GET flow with session "
            "cookies (InvokeDownloadMeetingDocument or InvokeDownloadAttachment, "
            "then ViewDocument) -- handled by app/ingestion/onbase_agenda.py, "
            "not the generic connector dispatch. Minutes (documentType=2) exist "
            "on this platform but haven't been ingested in an end-to-end test "
            "yet; agenda + packet (types 1 and 5) have been."
        ),
    ),
    dict(
        name="Santa Cruz County Planning Commission — Legacy Meeting Search",
        jurisdiction="Santa Cruz County",
        agency="Community Development and Infrastructure",
        body="Planning Commission",
        source_type="meeting_body_page",
        authority_level="official_primary",
        url="https://www2.santacruzcountyca.gov/planning/plnmeetings/Search/PLNsrchHome.asp",
        fetch_method="scc_planning_search",
        connector="none",
        polling_interval_minutes=1440,
        parser_type="scc_planning_search",
        notes=(
            "Does NOT share the county's PrimeGov tenant (unlike Ventura, where "
            "Board of Supervisors and Planning Commission were on the same "
            "platform, just different committee ids). This is a Microsoft "
            "Indexing Service-era classic-ASP full-text search tool (confirmed "
            "live 2026-07-10), no browsable listing page -- app/ingestion/"
            "scc_planning_search.py runs the session-stateful 3-request search "
            "flow with 'agenda' as the search keyword (matches virtually every "
            "real document by definition) and MeetingType=1 for Planning "
            "Commission. Not the generic connector dispatch for the same "
            "session-state reason as the OnBase source above."
        ),
    ),
    dict(
        name="Santa Cruz County Board of Supervisors — PrimeGov Portal",
        jurisdiction="Santa Cruz County",
        agency="Board of Supervisors",
        body="Board of Supervisors",
        source_type="meeting_body_page",
        authority_level="official_primary",
        url="https://santacruzcountyca.primegov.com/public/portal?committee=1",
        fetch_method="html_pdf_harvest",
        connector="primegov",
        polling_interval_minutes=240,
        parser_type="primegov_api",
        notes=(
            "Confirmed live 2026-07-10 via the open, unauthenticated JSON API "
            "(api/v2/PublicPortal/ListArchivedMeetingsByCommitteeId) -- same "
            "PrimeGov platform/API shape as Ventura's instance, committeeId=1 for "
            "Board of Supervisors. Checked committeeIds 1-20 on this tenant: only "
            "Board of Supervisors (1), two Flood Control & Water Conservation "
            "District zones (3, 4), Assessment Appeals Board (5), Consolidated "
            "Redevelopment Successor Agency Oversight Board (6), Library Financing "
            "Authority (7), and City Selection Committee (8) exist here -- no "
            "Planning Commission on this PrimeGov tenant (see the Planning "
            "Commission TODO in README.md; unlike Ventura, it's on a separate "
            "legacy platform)."
        ),
    ),
    dict(
        name="NetFile — Santa Cruz County Campaign Finance Filings (RSS)",
        jurisdiction="Santa Cruz County",
        agency="Elections / Campaign Finance",
        body=None,
        source_type="campaign_filing_feed",
        authority_level="official_primary",
        url="https://netfile.com/connect2/api/public/list/filing/rss/SCCO/campaign.xml",
        fetch_method="rss_feed",
        connector="netfile_rss",
        polling_interval_minutes=360,
        parser_type="generic_pdf_harvest",
        notes=(
            "Confirmed live 2026-07-10: real filings (e.g. a teachers'-union PAC, "
            "a San Lorenzo Valley Water District director race, a county "
            "supervisor race), same rolling-window RSS platform as Ventura's VCO "
            "feed. Note this county code (SCCO) and the separate City of Santa "
            "Cruz code (CRUZ, below) are genuinely distinct feeds -- see "
            "EXPANSION_STRATEGY.md in the Ventura repo for why the city/county "
            "boundary matters here."
        ),
    ),
    dict(
        name="NetFile — Santa Cruz County Statement of Economic Interests (RSS)",
        jurisdiction="Santa Cruz County",
        agency="Elections / Campaign Finance",
        body=None,
        source_type="campaign_filing_feed",
        authority_level="official_primary",
        url="https://netfile.com/connect2/api/public/list/filing/rss/SCCO/sei.xml",
        fetch_method="rss_feed",
        connector="netfile_rss",
        polling_interval_minutes=360,
        parser_type="generic_pdf_harvest",
        notes="Form 700 disclosures, same platform as the SCCO campaign feed above.",
    ),
    dict(
        name="NetFile — City of Santa Cruz Campaign Finance Filings (RSS)",
        jurisdiction="City of Santa Cruz",
        agency="City Clerk / Campaign Finance",
        body=None,
        source_type="campaign_filing_feed",
        authority_level="official_primary",
        url="https://netfile.com/connect2/api/public/list/filing/rss/CRUZ/campaign.xml",
        fetch_method="rss_feed",
        connector="netfile_rss",
        polling_interval_minutes=360,
        parser_type="generic_pdf_harvest",
        notes=(
            "Confirmed live 2026-07-10: the City of Santa Cruz runs its own "
            "separate NetFile portal (agency code CRUZ) distinct from the "
            "county's (SCCO) -- not every jurisdiction's campaign finance is "
            "county-level only."
        ),
    ),
    dict(
        name="NetFile — City of Santa Cruz Statement of Economic Interests (RSS)",
        jurisdiction="City of Santa Cruz",
        agency="City Clerk / Campaign Finance",
        body=None,
        source_type="campaign_filing_feed",
        authority_level="official_primary",
        url="https://netfile.com/connect2/api/public/list/filing/rss/CRUZ/sei.xml",
        fetch_method="rss_feed",
        connector="netfile_rss",
        polling_interval_minutes=360,
        parser_type="generic_pdf_harvest",
        notes="Form 700 disclosures, same platform as the CRUZ campaign feed above.",
    ),
    dict(
        name="Santa Cruz County Elections Division",
        jurisdiction="Santa Cruz County",
        agency="County Clerk / Elections",
        body=None,
        source_type="election_page",
        authority_level="official_primary",
        url="https://votescount.santacruzcountyca.gov/Home/CandidatesandMeasures.aspx",
        fetch_method="html_pdf_harvest",
        connector="generic",
        polling_interval_minutes=1440,
        parser_type="generic_pdf_harvest",
        notes=(
            "Confirmed live 2026-07-10: plain HTML with direct PDF links "
            "(/Portals/16/.../*.pdf), no bot wall -- unlike Ventura's Elections "
            "page (AWS WAF-blocked), this one works fine even with this "
            "project's own honest User-Agent."
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
