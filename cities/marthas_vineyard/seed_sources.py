"""Seed the source registry (see prd.md section 13.1 for the schema this
follows). Safe to re-run -- existing sources are matched by URL and left
alone rather than duplicated.

FORKED FROM VENTURA/SANTA CRUZ/BOSTON CIVIC RADAR. Source research done
2026-09-10 (live verification against real endpoints -- see README.md for
the full per-jurisdiction writeup). Martha's Vineyard is six small towns
(Aquinnah, Chilmark, Edgartown, Oak Bluffs, Tisbury, West Tisbury) plus
Dukes County and the Martha's Vineyard Commission, a regional land-use
regulatory body unique to this jurisdiction (no equivalent in any prior
fork) -- reconnaissance covered all of that, not just the two towns that
turned out to be viable. Two towns (Oak Bluffs, Tisbury) cleanly matched
the existing CivicPlus AgendaCenter connector -- zero new code, same as
most of Ventura's sources. MA OCPF campaign finance also reuses the
connector Boston already built (now generalized to a per-source allowlist,
see app/ingestion/connectors/ocpf.py). Everything else found during
reconnaissance is a real, confirmed gap, not silence: three towns
(Edgartown, Chilmark, Aquinnah) return HTTP 403 from an edge bot-wall
(Akamai/Cloudflare, confirmed via curl with a real browser UA, not just a
missing-page 404) -- consistent with this project's standing policy against
bypassing access controls (see Ventura's Elections/AWS-WAF gap for
precedent); West Tisbury runs a bespoke legacy PHP calendar system
(`agenda_and_minutes/index.php?view=month&...`), not CivicPlus, needing new
connector code not yet written; Dukes County's site (dukescounty.gov) runs
"EvoGov", a platform not seen in any prior fork, with a `/meetings` listing
that's reachable but unparsed -- also needs new connector code; the Martha's
Vineyard Commission -- arguably the single most consequential body for this
project's purpose, since it's the island's actual land-use/development
review authority -- is Akamai-bot-walled the same way the three towns above
are. None of these four gaps are stubbed in below; they're real work for a
follow-up pass, not a config change.

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
        name="Town of Oak Bluffs — AgendaCenter",
        jurisdiction="Town of Oak Bluffs",
        agency="Town of Oak Bluffs",
        body=None,
        source_type="agenda_center",
        authority_level="official_primary",
        url="https://www.oakbluffsma.gov/AgendaCenter",
        fetch_method="html_pdf_harvest",
        connector="civicplus_agenda_center",
        polling_interval_minutes=240,
        parser_type="civicplus_agenda_center",
        notes=(
            "Confirmed live 2026-09-10: real CivicPlus AgendaCenter (footer "
            "confirms 'Government Websites by CivicPlus'), 816 document "
            "links across the accordion at fetch time, same connector "
            "Ventura's City Council source already uses -- pure config "
            "addition, no new code."
        ),
    ),
    dict(
        name="Town of Tisbury — AgendaCenter",
        jurisdiction="Town of Tisbury",
        agency="Town of Tisbury",
        body=None,
        source_type="agenda_center",
        authority_level="official_primary",
        url="https://www.tisburyma.gov/AgendaCenter",
        fetch_method="html_pdf_harvest",
        connector="civicplus_agenda_center",
        polling_interval_minutes=240,
        parser_type="civicplus_agenda_center",
        notes=(
            "Confirmed live 2026-09-10: real CivicPlus AgendaCenter, 524 "
            "document links, 17 board/committee categories confirmed via "
            "the page's own accordion headers (Select Board, Planning "
            "Board, Conservation Commission, Water Works, etc.) -- pure "
            "config addition, same as Oak Bluffs above."
        ),
        known_limitations=(
            "Tisbury is Martha's Vineyard's most populous town and the "
            "island's ferry-terminal town (Vineyard Haven), so this is the "
            "single highest-signal source in this fork -- but it's still "
            "just one of six towns; see this file's module docstring for "
            "the other five towns' status."
        ),
    ),
    dict(
        name="Massachusetts OCPF — Martha's Vineyard-Area Filings",
        jurisdiction="Dukes County",
        agency="Office of Campaign and Political Finance",
        body="Martha's Vineyard",
        source_type="campaign_finance_feed",
        authority_level="official_primary",
        url="https://api.ocpf.us/reports/log",
        fetch_method="json_api_harvest",
        connector="ocpf",
        polling_interval_minutes=240,
        parser_type="ocpf",
        known_limitations=(
            "/reports/log returns only the ~50 most recent filings "
            "statewide, no pagination or date-range params -- same caveat "
            "as Boston's OCPF source. Also: none of MV's six towns have "
            "their own OCPF-registered local candidates (Select Board seats "
            "etc. are too small to trigger state filing requirements -- "
            "they file locally with the town clerk instead, which has no "
            "public online feed this project has found). This source only "
            "covers the state/county-level races whose districts cover MV: "
            "State Senate (Cape & Islands), State House (Barnstable, Dukes "
            "& Nantucket), Dukes County Sheriff, and the Cape & Islands "
            "District Attorney."
        ),
        notes=(
            "Confirmed live 2026-09-10: verified against GET /municipalities "
            "for both Aquinnah (cityCode 104) and Tisbury (cityCode 296) -- "
            "identical electedFilers set on both, as expected since all six "
            "MV towns share the same state Senate/House districts and the "
            "same county Sheriff/DA. Scoped via "
            "app/ingestion/connectors/ocpf.py's "
            "CPF_ID_ALLOWLISTS[\"Martha's Vineyard\"] (keyed by this "
            "Source's body field, now that Boston's OCPF source and this "
            "one share the same connector -- see that module's docstring)."
        ),
    ),
    dict(
        name="Martha's Vineyard Commission — YouTube Channel Captions",
        jurisdiction="Martha's Vineyard Commission",
        agency="Martha's Vineyard Commission",
        body=None,
        source_type="meeting_video_captions",
        authority_level="official_primary",
        url="https://www.youtube.com/@mvcommission/videos",
        fetch_method="youtube_channel_captions",
        connector="generic",  # unused for this fetch_method -- see worker._bespoke_ingestors()
        polling_interval_minutes=1440,
        parser_type=None,
        notes=(
            "Confirmed live 2026-09-10: 115 videos, real MVC governance "
            "content present (full Commission meetings 2022-2023, ongoing "
            "Land Use Planning Committee / Housing Action Task Force / "
            "Joint Affordable Housing Group / Climate Action Task Force / "
            "Manuel Correllus State Forest Task Force / Water Alliance "
            "meetings through 2026) alongside non-governance noise (GIS "
            "tutorials, drone footage, oral-history interviews) filtered "
            "out by title keyword in app/ingestion/youtube_captions.py. "
            "Uses YouTube's free auto-generated captions via yt-dlp -- no "
            "API key, no WhisperX/GPU needed, confirmed live against a "
            "real Water Alliance meeting video. This is the closest "
            "available substitute for the MVC's own site, which is "
            "Akamai-bot-walled (see this file's module docstring)."
        ),
        known_limitations=(
            "Title-based date/body matching to a Meeting row is best-effort "
            "(same class of limitation as meeting_audio.py's Granicus "
            "matching) -- titles that don't parse to a date, or that don't "
            "match this module's governance-keyword allowlist, are either "
            "left unlinked or silently skipped. Polled daily "
            "(polling_interval_minutes=1440) rather than the 240-minute "
            "default used elsewhere, since this channel uploads "
            "infrequently and yt-dlp's channel listing is comparatively "
            "expensive."
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
