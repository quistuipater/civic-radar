"""Connector for boston.gov's public-notices board (Drupal-based), verified
live 2026-07-10. Structurally different from every other document source in
this project: each notice is its own individually-addressed HTML detail page
(`/public-notices/{id}`), not a linked PDF/Word/CSV attachment, so
`generic.py` (which only harvests links ending in `.pdf`/`.doc`/`.docx`/
`.csv`) finds nothing on this listing. This connector instead treats each
`/public-notices/{id}` link on the listing page as the document itself --
closer to a sitemap crawl than a document harvester -- and lets the generic
`_fetch_and_store_document()` pipeline archive the notice page's raw HTML
(it already handles `text/html` via `EXT_BY_CONTENT_TYPE`, no special-casing
needed here).

`base_url` is expected to be boston.gov's public-notices listing filtered to
one department via its own `field_contact_target_id[]` facet, e.g.
`https://www.boston.gov/public-notices?field_contact_target_id%5B%5D=551`
(551 = Elections, confirmed live 2026-07-10 -- the site exposes ~100 other
department ids in the same `<select>`, see that department's Source
comments before assuming this connector needs new code for a differently
-scoped notices source; it's the same platform, just a different facet
value). No pagination handling: the Elections facet returns a small number
of live/upcoming notices at any given time, well under one page.
"""

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from app.archive import sha256_hex
from app.ingestion.connectors.base import DiscoveredDocument

# Every field here is regenerated per-request by boston.gov's Drupal/Incapsula
# stack and carries no notice content -- confirmed live 2026-09-06 by diffing
# two page fetches a day apart: the only differences were the CSRF
# form_build_id, a randomized view wrapper id, the breadcrumb element id, a
# rotating "suggested search" widget, and Incapsula's cache-busting `cb=`
# param. Hashing the raw page for change detection against these made the
# pipeline archive a brand new "page snapshot" Document on effectively every
# poll, even on days with zero actual notice changes. Strip them before
# hashing so identical notice content dedupes as identical.
_VOLATILE_PATTERNS = [
    re.compile(rb'data-drupal-selector="form-[a-z0-9]+"'),
    re.compile(rb'name="form_build_id" value="[^"]*"'),
    re.compile(rb"js-view-dom-id-[a-f0-9]+"),
    re.compile(rb'id="breadcrumb-[a-f0-9]+"'),
    re.compile(rb"data-bos-ai-search-window-query=\"[^\"]*\""),
    re.compile(rb"_Incapsula_Resource\?SWJIYLWA=[^&\"]*&ns=\d+&cb=\d+"),
]


def stable_content_hash(body: bytes) -> str:
    """Content hash for change-detection purposes only -- strips known
    per-request-random boilerplate (see _VOLATILE_PATTERNS) so the page's
    hash only changes when its actual notice content does. The raw body is
    still archived unmodified; only the hash used for dedup is normalized."""
    normalized = body
    for pattern in _VOLATILE_PATTERNS:
        normalized = pattern.sub(b"", normalized)
    return sha256_hex(normalized)


def discover(html_bytes: bytes, base_url: str, source_body: str | None = None) -> list[DiscoveredDocument]:
    soup = BeautifulSoup(html_bytes, "lxml")
    found: dict[str, DiscoveredDocument] = {}

    for a in soup.select('a[href^="/public-notices/"]'):
        href = a.get("href", "").strip()
        tail = href.removeprefix("/public-notices/")
        if not tail.isdigit():
            continue
        full_url = urljoin(base_url, href)
        if full_url in found:
            continue
        title = a.get("title", "").strip() or a.get_text(strip=True) or None
        found[full_url] = DiscoveredDocument(url=full_url, document_type="notice", title=title)
    return list(found.values())
