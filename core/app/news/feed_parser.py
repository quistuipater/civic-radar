"""Parses RSS 2.0 XML into structured news items. Covers both feed shapes
this pipeline consumes -- standard WordPress RSS (wordpress_rss connector)
and Google News search-RSS (google_news_proxy connector) -- both are plain
RSS 2.0 under the hood, so one parser handles both; the connector
distinction only matters to news/retrieval.py, for what happens with the
parsed item afterward (whether a full-text fetch is attempted).
"""

from dataclasses import dataclass
from datetime import datetime
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree


@dataclass
class NewsItem:
    title: str
    link: str
    summary: str | None
    published_at: datetime | None


def parse_feed(xml_bytes: bytes) -> list[NewsItem]:
    try:
        root = ElementTree.fromstring(xml_bytes)
    except ElementTree.ParseError:
        return []

    items: list[NewsItem] = []
    for item in root.iter("item"):
        link = (item.findtext("link") or "").strip()
        title = (item.findtext("title") or "").strip()
        if not link or not title:
            continue
        description = (item.findtext("description") or "").strip() or None
        published_at = _parse_pub_date((item.findtext("pubDate") or "").strip())
        items.append(NewsItem(title=title, link=link, summary=description, published_at=published_at))
    return items


def _parse_pub_date(raw: str) -> datetime | None:
    if not raw:
        return None
    try:
        return parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
