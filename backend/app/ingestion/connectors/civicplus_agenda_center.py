"""Connector for CivicPlus AgendaCenter sites (e.g. cityofventura.ca.gov/AgendaCenter).

The whole site's agenda center lives on one page as an accordion: each category
panel is one governing body (City Council, Planning Commission, ...), and each
row within it links to /AgendaCenter/ViewFile/{Agenda|Minutes}/_MMDDYYYY-<id>,
which serves the PDF directly. Verified against the live site on 2026-07-05:
21 categories, 210 document links, aria-labels of the form
"July 07, 2026, City Council Closed Session/Regular Meeting. Agenda".
"""

import re
from datetime import date
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from dateutil import parser as dateutil_parser

from app.ingestion.connectors.base import DiscoveredDocument

LABEL_RE = re.compile(
    r"^(?P<datepart>[A-Za-z]+ \d{1,2},\s*\d{4}),\s*(?P<desc>.+)\.\s*(?P<doctype>\w+)\s*$",
    re.S,
)


def discover(html_bytes: bytes, base_url: str, source_body: str | None = None) -> list[DiscoveredDocument]:
    # source_body is intentionally unused here -- this connector derives a
    # more accurate per-document body from each accordion category
    # (category_name below), since one AgendaCenter source covers many
    # governing bodies at once.
    soup = BeautifulSoup(html_bytes, "lxml")
    results: dict[str, DiscoveredDocument] = {}

    for header in soup.select('h2[data-cp-toggle="collapse"]'):
        category_name = header.get_text(strip=True)
        controls = header.get("aria-controls")
        container = soup.find(id=controls) if controls else None
        if container is None:
            continue

        for a in container.select('a[aria-label][href*="/AgendaCenter/ViewFile/"]'):
            href = a.get("href", "").strip()
            if not href:
                continue
            full_url = urljoin(base_url, href)
            if full_url in results:
                continue

            label = a["aria-label"]
            meeting_date, meeting_desc, doctype = _parse_label(label)

            results[full_url] = DiscoveredDocument(
                url=full_url,
                document_type=doctype.lower() if doctype else "agenda",
                title=meeting_desc or label,
                meeting_date=meeting_date,
                body=category_name,
                meeting_type=meeting_desc,
            )
    return list(results.values())


def _parse_label(label: str) -> tuple[date | None, str | None, str | None]:
    m = LABEL_RE.match(label)
    if not m:
        return None, None, None
    try:
        meeting_date = dateutil_parser.parse(m.group("datepart")).date()
    except (ValueError, OverflowError):
        meeting_date = None
    return meeting_date, m.group("desc").strip(), m.group("doctype").strip()
