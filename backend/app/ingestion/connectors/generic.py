"""Fallback connector: harvest any linked PDF/Word/CSV documents from an HTML page.

Used for sources that don't have a bespoke connector yet (prd.md 26.1 "Source
Fragility" — many local-government sites are JS-rendered SPAs like Legistar or
NetFile and won't yield document links from a plain HTTP GET. In that case this
still archives the raw page snapshot so nothing is silently missed; the gap is
recorded on the source's `known_limitations` field rather than hidden.
"""

from urllib.parse import urljoin

from bs4 import BeautifulSoup

from app.ingestion.connectors.base import DiscoveredDocument

DOC_EXTENSIONS = (".pdf", ".doc", ".docx", ".csv")


def discover(html_bytes: bytes, base_url: str, source_body: str | None = None) -> list[DiscoveredDocument]:
    soup = BeautifulSoup(html_bytes, "lxml")
    found: dict[str, DiscoveredDocument] = {}

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("javascript:", "mailto:", "#")):
            continue
        lower = href.lower().split("?")[0]
        if not lower.endswith(DOC_EXTENSIONS):
            continue
        full_url = urljoin(base_url, href)
        if full_url in found:
            continue
        link_text = a.get_text(strip=True) or None
        found[full_url] = DiscoveredDocument(
            url=full_url,
            document_type=_guess_doc_type(link_text, full_url),
            title=link_text,
        )
    return list(found.values())


def _guess_doc_type(link_text: str | None, url: str) -> str:
    haystack = f"{link_text or ''} {url}".lower()
    if "minute" in haystack:
        return "minutes"
    if "notice" in haystack:
        return "notice"
    if "packet" in haystack:
        return "packet"
    if "agenda" in haystack:
        return "agenda"
    return "pdf"
