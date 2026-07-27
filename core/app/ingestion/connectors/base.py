from dataclasses import dataclass
from datetime import date


@dataclass
class DiscoveredDocument:
    """A single document link found on a source page, before it's downloaded."""

    url: str
    document_type: str  # agenda | minutes | notice | packet | pdf | source_page_snapshot | ...
    title: str | None = None
    meeting_date: date | None = None
    body: str | None = None
    meeting_type: str | None = None
