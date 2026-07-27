"""Tests for the PrimeGov connector.

Writing these caught a real, live bug: `body` was hardcoded to "Board of
Supervisors" regardless of which committee was actually being fetched, even
though this same connector is shared across multiple committees (Board of
Supervisors id=1, Planning Commission id=85, ...). Verified live 2026-07-08:
14 Planning Commission documents and 8 meetings in the DB had the wrong
`body` before the fix (corrected via a one-off UPDATE; no cross-contamination
since no two committees' meetings ever landed on the same date). The fix
makes the connector take the source's own `body` as a parameter instead of
guessing, so `test_uses_source_body_parameter_instead_of_hardcoding` below is
the regression test for that specific bug.
"""

import httpx

import app.ingestion.connectors.primegov as primegov_module
from app.ingestion.connectors.primegov import _parse_meeting_date, discover


def fake_json_response(payload) -> httpx.Response:
    import json

    return httpx.Response(200, content=json.dumps(payload).encode(), headers={"content-type": "application/json"})


def meeting(
    committee_id=85,
    date_time="2026-01-22T08:30:00",
    date_str="Jan 22, 2026",
    documents=None,
):
    return {
        "id": 3928,
        "committeeId": committee_id,
        "dateTime": date_time,
        "date": date_str,
        "documentList": documents or [],
    }


def doc_entry(template_id=24686, template_name="Agenda", compile_output_type=1):
    return {
        "id": 34198,
        "templateId": template_id,
        "templateName": template_name,
        "compileOutputType": compile_output_type,
    }


class TestPrimegovDiscover:
    def _mock_meetings(self, monkeypatch, upcoming=None, archived=None):
        def fake_fetch(url, **kwargs):
            if "ListUpcomingMeetings" in url:
                return fake_json_response(upcoming or [])
            return fake_json_response(archived or [])

        monkeypatch.setattr(primegov_module, "fetch_url", fake_fetch)

    def test_uses_source_body_parameter_instead_of_hardcoding(self, monkeypatch):
        # Regression test for the live bug: Planning Commission (committee=85)
        # documents must be labeled "Planning Commission", not "Board of
        # Supervisors", when the caller passes the source's real body through.
        self._mock_meetings(monkeypatch, archived=[meeting(documents=[doc_entry()])])

        found = discover(
            b"", "https://ventura.primegov.com/public/portal?committee=85", source_body="Planning Commission"
        )

        assert len(found) == 1
        assert found[0].body == "Planning Commission"

    def test_defaults_to_board_of_supervisors_when_no_body_given(self, monkeypatch):
        # Backward-compat default for callers that don't pass source_body.
        self._mock_meetings(monkeypatch, archived=[meeting(documents=[doc_entry()])])

        found = discover(b"", "https://ventura.primegov.com/public/portal?committee=1")

        assert found[0].body == "Board of Supervisors"

    def test_parses_committee_id_from_query_string(self, monkeypatch):
        seen_urls = []

        def fake_fetch(url, **kwargs):
            seen_urls.append(url)
            return fake_json_response([])

        monkeypatch.setattr(primegov_module, "fetch_url", fake_fetch)

        discover(b"", "https://ventura.primegov.com/public/portal?committee=85")

        assert any("committeeId=85" in u for u in seen_urls)

    def test_defaults_committee_id_to_1_when_missing_from_url(self, monkeypatch):
        seen_urls = []

        def fake_fetch(url, **kwargs):
            seen_urls.append(url)
            return fake_json_response([])

        monkeypatch.setattr(primegov_module, "fetch_url", fake_fetch)

        discover(b"", "https://ventura.primegov.com/public/portal")

        assert any("committeeId=1" in u for u in seen_urls)

    def test_skips_html_agenda_rendition_keeps_pdf_rendition(self, monkeypatch):
        documents = [
            doc_entry(template_id=1, template_name="HTML Agenda", compile_output_type=3),
            doc_entry(template_id=2, template_name="Agenda", compile_output_type=1),
        ]
        self._mock_meetings(monkeypatch, archived=[meeting(documents=documents)])

        found = discover(b"", "https://ventura.primegov.com/public/portal?committee=1")

        assert len(found) == 1
        assert found[0].document_type == "agenda"

    def test_skips_documents_with_unrecognized_template_name(self, monkeypatch):
        documents = [doc_entry(template_name="Some New Report Type")]
        self._mock_meetings(monkeypatch, archived=[meeting(documents=documents)])

        found = discover(b"", "https://ventura.primegov.com/public/portal?committee=1")

        assert found == []

    def test_maps_template_names_to_our_document_types(self, monkeypatch):
        documents = [
            doc_entry(template_id=1, template_name="Agenda"),
            doc_entry(template_id=2, template_name="Packet"),
            doc_entry(template_id=3, template_name="Minute Orders"),
        ]
        self._mock_meetings(monkeypatch, archived=[meeting(documents=documents)])

        found = discover(b"", "https://ventura.primegov.com/public/portal?committee=1")

        types = {d.document_type for d in found}
        assert types == {"agenda", "packet", "minutes"}

    def test_merges_upcoming_and_archived_meetings(self, monkeypatch):
        self._mock_meetings(
            monkeypatch,
            upcoming=[meeting(date_time="2026-08-01T08:30:00", documents=[doc_entry(template_id=1)])],
            archived=[meeting(date_time="2026-01-22T08:30:00", documents=[doc_entry(template_id=2)])],
        )

        found = discover(b"", "https://ventura.primegov.com/public/portal?committee=1")

        assert len(found) == 2

    def test_deduplicates_documents_appearing_in_multiple_meetings(self, monkeypatch):
        same_doc = doc_entry(template_id=99)
        self._mock_meetings(
            monkeypatch,
            upcoming=[meeting(documents=[same_doc])],
            archived=[meeting(documents=[same_doc])],
        )

        found = discover(b"", "https://ventura.primegov.com/public/portal?committee=1")

        assert len(found) == 1

    def test_returns_empty_list_when_api_call_raises(self, monkeypatch):
        def raise_error(url, **kwargs):
            raise httpx.ConnectError("connection refused")

        monkeypatch.setattr(primegov_module, "fetch_url", raise_error)

        assert discover(b"", "https://ventura.primegov.com/public/portal?committee=1") == []

    def test_document_with_no_template_id_is_skipped(self, monkeypatch):
        broken_doc = doc_entry()
        broken_doc["templateId"] = None
        self._mock_meetings(monkeypatch, archived=[meeting(documents=[broken_doc])])

        assert discover(b"", "https://ventura.primegov.com/public/portal?committee=1") == []


class TestParseMeetingDate:
    def test_parses_iso_datetime_string(self):
        assert str(_parse_meeting_date("2026-01-22T08:30:00")) == "2026-01-22"

    def test_returns_none_for_missing_or_malformed_input(self):
        assert _parse_meeting_date(None) is None
        assert _parse_meeting_date("not-a-date") is None
