"""Connector for static informational pages where the page's own text is
the payload -- e.g. a city's "Form of Government" or department-directory
pages -- as opposed to pages that link out to PDFs to harvest (generic.py).

Always discovers zero linked documents: there's nothing to harvest, because
the source-level page snapshot fetch_source_once() already archives is
itself the thing worth parsing. See pipeline.py's parser_status branch for
Source.source_type == "static_reference_page", which is what makes that
snapshot flow through parsing/AI extraction instead of being skipped like
an ordinary source_page_snapshot.
"""

from app.ingestion.connectors.base import DiscoveredDocument


def discover(html_bytes: bytes, base_url: str, source_body: str | None = None) -> list[DiscoveredDocument]:
    return []
