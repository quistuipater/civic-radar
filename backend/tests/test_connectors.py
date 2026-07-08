"""Pure parsing-logic tests for the document-discovery connectors -- no
network, no DB. These are the functions most likely to silently break when a
source's page structure changes, so they're the highest-value place to catch
a regression before it ships.
"""

from app.ingestion.connectors import generic, netfile_rss


class TestGenericDiscover:
    def test_finds_pdf_links_and_resolves_relative_urls(self):
        html = b"""
        <html><body>
          <a href="/AgendaCenter/ViewFile/Agenda/2026-06-01">June Agenda</a>
          <a href="/AgendaCenter/ViewFile/Minutes/2026-06-01.pdf">June Minutes</a>
        </body></html>
        """
        found = generic.discover(html, "https://cityofventura.ca.gov/AgendaCenter")
        # First link has no extension at all -- shouldn't match DOC_EXTENSIONS.
        assert len(found) == 1
        assert found[0].url == "https://cityofventura.ca.gov/AgendaCenter/ViewFile/Minutes/2026-06-01.pdf"
        assert found[0].document_type == "minutes"

    def test_ignores_non_document_links(self):
        html = b"""
        <html><body>
          <a href="#top">Back to top</a>
          <a href="javascript:void(0)">Menu</a>
          <a href="mailto:clerk@cityofventura.ca.gov">Email</a>
          <a href="/about-us">About</a>
        </body></html>
        """
        assert generic.discover(html, "https://example.com") == []

    def test_deduplicates_repeated_links(self):
        html = b"""
        <html><body>
          <a href="/notice.pdf">Notice</a>
          <a href="/notice.pdf">Same notice, different link text</a>
        </body></html>
        """
        found = generic.discover(html, "https://example.com")
        assert len(found) == 1

    def test_guesses_document_type_from_link_text_over_url(self):
        html = b'<a href="/file.pdf">Public Notice of Hearing</a>'
        found = generic.discover(html, "https://example.com")
        assert found[0].document_type == "notice"

    def test_falls_back_to_pdf_type_when_nothing_matches(self):
        html = b'<a href="/file.pdf">Attachment A</a>'
        found = generic.discover(html, "https://example.com")
        assert found[0].document_type == "pdf"


class TestNetfileRssDiscover:
    RSS_ITEM = """<?xml version="1.0"?>
    <rss><channel>
      <item>
        <title>Rooney, Mary Anne</title>
        <description>FPPC Form 470 (1/1/2026 - 12/31/2026)</description>
        <link>https://netfile.com/Connect2/api/public/image/12345</link>
      </item>
    </channel></rss>
    """

    def test_parses_feed_items_into_notices(self):
        found = netfile_rss.discover(self.RSS_ITEM.encode(), "https://netfile.com/feed.xml")
        assert len(found) == 1
        assert found[0].url == "https://netfile.com/Connect2/api/public/image/12345"
        assert found[0].document_type == "notice"
        assert found[0].title == "Rooney, Mary Anne — FPPC Form 470 (1/1/2026 - 12/31/2026)"

    def test_skips_items_with_no_link(self):
        rss = """<?xml version="1.0"?>
        <rss><channel><item><title>No link here</title></item></channel></rss>
        """
        assert netfile_rss.discover(rss.encode(), "https://netfile.com/feed.xml") == []

    def test_returns_empty_list_on_malformed_xml_instead_of_raising(self):
        assert netfile_rss.discover(b"<not><valid", "https://netfile.com/feed.xml") == []
