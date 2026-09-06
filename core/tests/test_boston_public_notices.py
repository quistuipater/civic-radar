"""Tests for the boston.gov public-notices connector, focused on
stable_content_hash -- see its docstring for the confirmed-live 2026-09-06
incident (Drupal/Incapsula per-request boilerplate causing spurious
duplicate page-snapshot Documents on every poll) that motivated it.
"""

from app.ingestion.connectors.boston_public_notices import discover, stable_content_hash


class TestStableContentHash:
    def test_identical_notice_content_hashes_the_same_despite_volatile_csrf_token(self):
        page_one = (
            b'<input data-drupal-selector="form-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" '
            b'name="form_build_id" value="form-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" />'
            b"<p>Zoning Board of Appeal Hearing</p>"
        )
        page_two = (
            b'<input data-drupal-selector="form-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb" '
            b'name="form_build_id" value="form-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb" />'
            b"<p>Zoning Board of Appeal Hearing</p>"
        )

        assert stable_content_hash(page_one) == stable_content_hash(page_two)

    def test_identical_content_despite_rotating_search_suggestions_and_incapsula_cache_buster(self):
        page_one = (
            b'<li><button data-bos-ai-search-window-query="311 services">311 services</button></li>'
            b'<script src="/_Incapsula_Resource?SWJIYLWA=abc123&ns=1&cb=1716736666"></script>'
            b"<p>real notice content</p>"
        )
        page_two = (
            b'<li><button data-bos-ai-search-window-query="Trash schedule">Trash schedule</button></li>'
            b'<script src="/_Incapsula_Resource?SWJIYLWA=abc123&ns=1&cb=714170011"></script>'
            b"<p>real notice content</p>"
        )

        assert stable_content_hash(page_one) == stable_content_hash(page_two)

    def test_actual_notice_content_change_still_changes_the_hash(self):
        page_one = b"<p>Zoning Board of Appeal Hearing</p>"
        page_two = b"<p>Licensing Board Hearing</p>"

        assert stable_content_hash(page_one) != stable_content_hash(page_two)


class TestDiscover:
    def test_discovers_each_notice_link_once(self):
        html = (
            b'<html><body>'
            b'<a href="/public-notices/111" title="Zoning Board of Appeal Hearing">Zoning Board of Appeal Hearing</a>'
            b'<a href="/public-notices/111" title="Zoning Board of Appeal Hearing">Zoning Board of Appeal Hearing</a>'
            b'<a href="/public-notices/222" title="Licensing Board Hearing">Licensing Board Hearing</a>'
            b"</body></html>"
        )

        found = discover(html, "https://www.boston.gov/public-notices?field_contact_target_id%5B%5D=56")

        urls = sorted(d.url for d in found)
        assert urls == [
            "https://www.boston.gov/public-notices/111",
            "https://www.boston.gov/public-notices/222",
        ]
