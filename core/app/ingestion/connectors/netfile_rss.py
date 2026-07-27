"""Connector for NetFile's public RSS filing feed -- not the interactive
search portal (netfile.com/public/<aid>/campaign), which sits behind an
active Cloudflare Turnstile challenge. NetFile separately publishes a
real-time, unauthenticated RSS feed per agency/filing-type (verified live
2026-07-06: plain HTTP GET, no Turnstile, e.g.
https://netfile.com/connect2/api/public/list/filing/rss/VCO/campaign.xml),
and each item's <link> is a direct, unauthenticated PDF download
(netfile.com/Connect2/api/public/image/<filing_id>).

base_url is expected to be the RSS feed URL itself. The feed only covers a
rolling window (NetFile: max 15 days or 1000 items per its own <description>),
so this is for ongoing monitoring going forward, not full historical backfill
-- poll often enough that the window doesn't lapse between ticks.
"""

from xml.etree import ElementTree

from app.ingestion.connectors.base import DiscoveredDocument


def discover(html_bytes: bytes, base_url: str, source_body: str | None = None) -> list[DiscoveredDocument]:
    try:
        root = ElementTree.fromstring(html_bytes)
    except ElementTree.ParseError:
        return []

    results: list[DiscoveredDocument] = []
    for item in root.iter("item"):
        link = (item.findtext("link") or "").strip()
        if not link:
            continue
        title = (item.findtext("title") or "").strip()
        description = (item.findtext("description") or "").strip()
        full_title = f"{title} — {description}" if description else title or None
        results.append(DiscoveredDocument(url=link, document_type="notice", title=full_title))
    return results
