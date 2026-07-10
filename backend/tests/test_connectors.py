"""Pure parsing-logic tests for the document-discovery connectors -- no
network, no DB. These are the functions most likely to silently break when a
source's page structure changes, so they're the highest-value place to catch
a regression before it ships.
"""

import json

from app.ingestion.connectors import boston_public_notices, generic, netfile_rss, ocpf


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

    def test_guesses_packet_type(self):
        html = b'<a href="/file.pdf">June Agenda Packet</a>'
        found = generic.discover(html, "https://example.com")
        assert found[0].document_type == "packet"

    def test_guesses_agenda_type(self):
        html = b'<a href="/file.pdf">June Agenda</a>'
        found = generic.discover(html, "https://example.com")
        assert found[0].document_type == "agenda"

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


class TestOcpfDiscover:
    BOSTON_CPF_ID = next(iter(ocpf.BOSTON_CPF_IDS))

    def _report(self, **overrides):
        report = {
            "cpfId": self.BOSTON_CPF_ID,
            "reportId": 1033109,
            "reportTypeDescription": "Deposit Report",
            "reportingPeriod": "7/6/26",
            "dateFiled": "Fri, 7/10/2026 1:04 PM",
            "fullNameReverse": "Wu, Michelle",
        }
        report.update(overrides)
        return report

    def test_keeps_only_boston_scoped_filers(self):
        body = json.dumps([self._report(), self._report(cpfId=999999, reportId=1)]).encode()
        found = ocpf.discover(body, "https://api.ocpf.us/reports/log")
        assert len(found) == 1
        assert found[0].url == "https://api.ocpf.us/report/pdf/1033109"
        assert found[0].document_type == "notice"
        assert found[0].title == "Wu, Michelle — Deposit Report (7/6/26)"

    def test_title_omits_period_when_missing(self):
        body = json.dumps([self._report(reportingPeriod=None)]).encode()
        found = ocpf.discover(body, "https://api.ocpf.us/reports/log")
        assert found[0].title == "Wu, Michelle — Deposit Report"

    def test_falls_back_to_default_filer_name_when_missing(self):
        body = json.dumps([self._report(fullNameReverse=None)]).encode()
        found = ocpf.discover(body, "https://api.ocpf.us/reports/log")
        assert found[0].title.startswith("Unknown filer")

    def test_skips_reports_with_no_report_id(self):
        body = json.dumps([self._report(reportId=None)]).encode()
        assert ocpf.discover(body, "https://api.ocpf.us/reports/log") == []

    def test_returns_empty_list_on_malformed_json_instead_of_raising(self):
        assert ocpf.discover(b"{not valid json", "https://api.ocpf.us/reports/log") == []

    def test_returns_empty_list_when_body_is_not_a_json_list(self):
        assert ocpf.discover(b'{"error": "nope"}', "https://api.ocpf.us/reports/log") == []


class TestBostonPublicNoticesDiscover:
    LISTING_HTML = """
    <html><body>
    <div class="n-li">
      <a href="/public-notices/16599736" title="Board of Election Commissioners Meeting">Board of Election Commissioners Meeting</a>
    </div>
    <div class="n-li">
      <a href="/public-notices/16599596" title="OPAT Civilian Review Board Public Meeting ">OPAT Civilian Review Board Public Meeting </a>
    </div>
    <nav><a href="/public-notices">Public Notices</a></nav>
    </body></html>
    """

    def test_finds_notice_links_and_resolves_relative_urls(self):
        found = boston_public_notices.discover(self.LISTING_HTML.encode(), "https://www.boston.gov/public-notices")
        assert len(found) == 2
        urls = {f.url for f in found}
        assert urls == {
            "https://www.boston.gov/public-notices/16599736",
            "https://www.boston.gov/public-notices/16599596",
        }

    def test_uses_title_attribute_and_strips_whitespace(self):
        found = boston_public_notices.discover(self.LISTING_HTML.encode(), "https://www.boston.gov/public-notices")
        titles = {f.title for f in found}
        assert "Board of Election Commissioners Meeting" in titles
        assert "OPAT Civilian Review Board Public Meeting" in titles

    def test_all_results_are_notice_type(self):
        found = boston_public_notices.discover(self.LISTING_HTML.encode(), "https://www.boston.gov/public-notices")
        assert all(f.document_type == "notice" for f in found)

    def test_ignores_the_bare_listing_link_itself(self):
        found = boston_public_notices.discover(self.LISTING_HTML.encode(), "https://www.boston.gov/public-notices")
        assert all(f.url != "https://www.boston.gov/public-notices" for f in found)

    def test_deduplicates_repeated_links(self):
        html = b"""
        <a href="/public-notices/1" title="First mention">First mention</a>
        <a href="/public-notices/1" title="Second mention, same notice">Second mention, same notice</a>
        """
        found = boston_public_notices.discover(html, "https://www.boston.gov/public-notices")
        assert len(found) == 1

    def test_ignores_non_numeric_notice_paths(self):
        html = b'<a href="/public-notices/page/2">Next page</a>'
        assert boston_public_notices.discover(html, "https://www.boston.gov/public-notices") == []

    def test_falls_back_to_link_text_when_no_title_attribute(self):
        html = b'<a href="/public-notices/123">Some Notice</a>'
        found = boston_public_notices.discover(html, "https://www.boston.gov/public-notices")
        assert found[0].title == "Some Notice"
