"""Tests for parse_feed -- covers both feed shapes this pipeline consumes
(WordPress RSS 2.0 and Google News search-RSS), which share the same XML
shape (<item><title>/<link>/<description>/<pubDate>), so one parser
handles both.
"""

from app.news.feed_parser import parse_feed

RSS_WITH_CONTENT_ENCODED = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/">
<channel>
<item>
  <title>City Council Approves New Zoning Rules</title>
  <link>https://example.invalid/article-1</link>
  <description>The council voted 4-1 to approve changes.</description>
  <content:encoded><![CDATA[<p>Full clean article body about the zoning vote, no site chrome.</p>]]></content:encoded>
</item>
</channel>
</rss>"""

VALID_RSS = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
<channel>
<title>Test Outlet</title>
<item>
  <title>City Council Approves New Zoning Rules</title>
  <link>https://example.invalid/article-1</link>
  <description>The council voted 4-1 to approve changes.</description>
  <pubDate>Fri, 01 Aug 2026 10:00:00 GMT</pubDate>
</item>
<item>
  <title>Local Bakery Wins Award</title>
  <link>https://example.invalid/article-2</link>
  <description>A feel-good story.</description>
  <pubDate>Thu, 31 Jul 2026 08:30:00 GMT</pubDate>
</item>
</channel>
</rss>"""


class TestParseFeed:
    def test_parses_valid_items(self):
        items = parse_feed(VALID_RSS)

        assert len(items) == 2
        assert items[0].title == "City Council Approves New Zoning Rules"
        assert items[0].link == "https://example.invalid/article-1"
        assert items[0].summary == "The council voted 4-1 to approve changes."
        assert items[0].published_at is not None
        assert items[0].published_at.year == 2026
        assert items[0].published_at.month == 8
        assert items[0].published_at.day == 1
        assert items[0].content_encoded is None

    def test_returns_empty_list_for_malformed_xml(self):
        items = parse_feed(b"not xml at all <<<")

        assert items == []

    def test_skips_items_missing_link(self):
        xml = b"""<rss><channel><item>
          <title>No Link Here</title>
          <description>desc</description>
        </item></channel></rss>"""

        assert parse_feed(xml) == []

    def test_skips_items_missing_title(self):
        xml = b"""<rss><channel><item>
          <link>https://example.invalid/no-title</link>
          <description>desc</description>
        </item></channel></rss>"""

        assert parse_feed(xml) == []

    def test_missing_pub_date_yields_none_not_error(self):
        xml = b"""<rss><channel><item>
          <title>Undated Article</title>
          <link>https://example.invalid/undated</link>
        </item></channel></rss>"""

        items = parse_feed(xml)

        assert len(items) == 1
        assert items[0].published_at is None
        assert items[0].summary is None

    def test_malformed_pub_date_yields_none_not_error(self):
        xml = b"""<rss><channel><item>
          <title>Bad Date Article</title>
          <link>https://example.invalid/bad-date</link>
          <pubDate>not a real date</pubDate>
        </item></channel></rss>"""

        items = parse_feed(xml)

        assert items[0].published_at is None


class TestParseFeedContentEncoded:
    def test_extracts_content_encoded_when_present(self):
        items = parse_feed(RSS_WITH_CONTENT_ENCODED)

        assert len(items) == 1
        assert items[0].content_encoded == "<p>Full clean article body about the zoning vote, no site chrome.</p>"

    def test_content_encoded_is_none_when_absent(self):
        xml = b"""<rss><channel><item>
          <title>No Content Encoded Here</title>
          <link>https://example.invalid/no-content-encoded</link>
          <description>desc</description>
        </item></channel></rss>"""

        items = parse_feed(xml)

        assert items[0].content_encoded is None
