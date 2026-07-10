"""Tests for the CivicPlus AgendaCenter connector -- the one covering the
most sources at once (21 categories/governing bodies on a single page), and
the one with the most fragile parsing (a regex over a free-text aria-label
plus dateutil date parsing). Unlike the PrimeGov bug, this connector already
derives `body` per-category rather than hardcoding it -- these tests pin
that down and probe the label-parsing edge cases (embedded periods,
malformed labels, unparsuadeable dates) that are exactly the kind of thing
that silently breaks when a city tweaks its AgendaCenter template.
"""

from app.ingestion.connectors.civicplus_agenda_center import _parse_label, discover

BASE_URL = "https://cityofventura.ca.gov/AgendaCenter"


def accordion_html(categories: list[tuple[str, str, list[tuple[str, str]]]]) -> bytes:
    """Build a minimal AgendaCenter-shaped accordion.

    categories: list of (category_name, container_id, [(href, aria_label), ...])
    """
    parts = ["<html><body>"]
    for name, container_id, links in categories:
        parts.append(f'<h2 data-cp-toggle="collapse" aria-controls="{container_id}">{name}</h2>')
        parts.append(f'<div id="{container_id}">')
        for href, label in links:
            parts.append(f'<a aria-label="{label}" href="{href}">{label}</a>')
        parts.append("</div>")
    parts.append("</body></html>")
    return "".join(parts).encode()


class TestDiscover:
    def test_extracts_category_as_body(self):
        html = accordion_html(
            [
                (
                    "City Council",
                    "cat1",
                    [("/AgendaCenter/ViewFile/Agenda/_07072026-123", "July 07, 2026, Regular Meeting. Agenda")],
                )
            ]
        )
        found = discover(html, BASE_URL)
        assert len(found) == 1
        assert found[0].body == "City Council"

    def test_handles_multiple_categories_independently(self):
        html = accordion_html(
            [
                (
                    "City Council",
                    "cat1",
                    [("/AgendaCenter/ViewFile/Agenda/_07072026-1", "July 07, 2026, Regular Meeting. Agenda")],
                ),
                (
                    "Planning Commission",
                    "cat2",
                    [("/AgendaCenter/ViewFile/Minutes/_06012026-2", "June 01, 2026, Hearing. Minutes")],
                ),
            ]
        )
        found = discover(html, BASE_URL)
        assert len(found) == 2
        by_body = {d.body: d for d in found}
        assert by_body["City Council"].document_type == "agenda"
        assert by_body["Planning Commission"].document_type == "minutes"

    def test_resolves_relative_urls_against_base(self):
        html = accordion_html(
            [("City Council", "cat1", [("/AgendaCenter/ViewFile/Agenda/_1", "July 07, 2026, Meeting. Agenda")])]
        )
        found = discover(html, BASE_URL)
        assert found[0].url == "https://cityofventura.ca.gov/AgendaCenter/ViewFile/Agenda/_1"

    def test_ignores_links_without_aria_label(self):
        html = (
            b'<html><body>'
            b'<h2 data-cp-toggle="collapse" aria-controls="cat1">City Council</h2>'
            b'<div id="cat1"><a href="/AgendaCenter/ViewFile/Agenda/_1">No label here</a></div>'
            b"</body></html>"
        )
        assert discover(html, BASE_URL) == []

    def test_ignores_links_outside_agendacenter_viewfile_path(self):
        html = accordion_html([("City Council", "cat1", [("/some/other/path.pdf", "July 07, 2026, Meeting. Agenda")])])
        assert discover(html, BASE_URL) == []

    def test_skips_category_when_aria_controls_target_is_missing(self):
        html = (
            b'<html><body>'
            b'<h2 data-cp-toggle="collapse" aria-controls="does-not-exist">City Council</h2>'
            b"</body></html>"
        )
        assert discover(html, BASE_URL) == []

    def test_deduplicates_repeated_hrefs_within_a_category(self):
        html = accordion_html(
            [
                (
                    "City Council",
                    "cat1",
                    [
                        ("/AgendaCenter/ViewFile/Agenda/_1", "July 07, 2026, Meeting. Agenda"),
                        ("/AgendaCenter/ViewFile/Agenda/_1", "July 07, 2026, Meeting. Agenda"),
                    ],
                )
            ]
        )
        found = discover(html, BASE_URL)
        assert len(found) == 1

    def test_malformed_label_falls_back_to_agenda_type_and_raw_label_as_title(self):
        html = accordion_html([("City Council", "cat1", [("/AgendaCenter/ViewFile/Agenda/_1", "Not a real label")])])
        found = discover(html, BASE_URL)
        assert len(found) == 1
        assert found[0].document_type == "agenda"
        assert found[0].title == "Not a real label"
        assert found[0].meeting_date is None

    def test_source_body_parameter_is_accepted_but_does_not_override_category(self):
        # civicplus derives a more accurate per-document body from the page
        # itself (one source spans many governing bodies) -- source_body
        # exists only for interface parity with the other connectors.
        html = accordion_html(
            [("City Council", "cat1", [("/AgendaCenter/ViewFile/Agenda/_1", "July 07, 2026, Meeting. Agenda")])]
        )
        found = discover(html, BASE_URL, source_body="Some Unrelated Body")
        assert found[0].body == "City Council"


class TestParseLabel:
    def test_parses_well_formed_label(self):
        meeting_date, desc, doctype = _parse_label("July 07, 2026, City Council Regular Meeting. Agenda")
        assert str(meeting_date) == "2026-07-07"
        assert desc == "City Council Regular Meeting"
        assert doctype == "Agenda"

    def test_desc_containing_a_period_still_splits_at_the_final_doctype(self):
        meeting_date, desc, doctype = _parse_label("July 07, 2026, Regular Meeting (Item No. 5). Minutes")
        assert desc == "Regular Meeting (Item No. 5)"
        assert doctype == "Minutes"

    def test_returns_all_none_when_label_does_not_match_expected_shape(self):
        assert _parse_label("completely unstructured text") == (None, None, None)

    def test_unparseable_date_portion_still_yields_desc_and_doctype(self):
        # The try/except around date parsing only covers the date itself --
        # a label that matches the overall shape but has a nonsense date
        # should still surface desc/doctype rather than losing everything.
        meeting_date, desc, doctype = _parse_label("Fooruary 40, 2026, Some Meeting. Agenda")
        assert meeting_date is None
        assert desc == "Some Meeting"
        assert doctype == "Agenda"

    def test_single_digit_day_parses_same_as_zero_padded(self):
        a, _, _ = _parse_label("July 7, 2026, Meeting. Agenda")
        b, _, _ = _parse_label("July 07, 2026, Meeting. Agenda")
        assert str(a) == str(b) == "2026-07-07"
