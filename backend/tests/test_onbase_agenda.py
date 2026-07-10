"""Tests for the City of Santa Cruz OnBase Agenda Online ingestion module.
Real markup/flow shapes here are copied from what was captured live against
ecm.cityofsantacruz.com on 2026-07-10 (see the module docstring) -- these
tests pin down the parsing/2-step-download logic against that shape, not
against OnBase itself.
"""

from urllib.parse import parse_qs, urlparse

import httpx
import pytest

import app.ingestion.onbase_agenda as onbase_agenda_module
from app.ingestion.onbase_agenda import _parse_meetings, _resolve_pdf, ingest_onbase_agenda
from app.models import Document, Meeting

from .conftest import make_source

HOMEPAGE_HTML = b"""
<html><body>
<table><tbody>
<tr id="meeting-2596-row" class="meeting-row" data-meeting-id="2596">
<td data-sortable-type="mtgType">Sister Cities</td>
<td data-sortable-type="mtgTime" data-sortable-data="1783990800">7/13/2026 6:00:00 PM</td>
<td>
<a href="/OnBaseAgendaOnline/Meetings/ViewMeeting?id=2596&doctype=1" id="lnkMeetingAgenda_2596">Agenda</a>
<a href="/OnBaseAgendaOnline/Documents/Downloadfile/Sister_Cities_2596_Agenda_7_13_2026.pdf?documentType=1&meetingId=2596" id="lnkMeetingAgendaDoc_2596" target="_blank">
<img src="/OnBaseAgendaOnline/Images/PDF_16x16.png" />
</a>
<a href="/OnBaseAgendaOnline/Documents/Downloadfile/Sister_Cities_2596_Agenda_Packet_7_13_2026.pdf?documentType=5&meetingId=2596&isAttachment=True" id="lnkAgendaPacket_2596" target="_blank">
Agenda Packet
</a>
</td>
</tr>
<tr id="meeting-2578-row" class="meeting-row" data-meeting-id="2578">
<td data-sortable-type="mtgType">City Council</td>
<td data-sortable-type="mtgTime" data-sortable-data="1768330800">1/13/2026 1:00:00 PM</td>
<td>
<a href="/OnBaseAgendaOnline/Documents/Downloadfile/City_Council_2578_Minutes_1_13_2026.pdf?documentType=2&meetingId=2578" id="lnkMinutesDoc_2578" target="_blank">Minutes</a>
</td>
</tr>
<!-- row with no document links at all -- should be skipped entirely -->
<tr id="meeting-9999-row" class="meeting-row" data-meeting-id="9999">
<td data-sortable-type="mtgType">Empty Body</td>
<td data-sortable-type="mtgTime" data-sortable-data="1768330800">1/13/2026 1:00:00 PM</td>
<td></td>
</tr>
</tbody></table>
</body></html>
"""


class FakeResponse:
    def __init__(self, content=b"", json_data=None, status_code=200):
        self.content = content
        self._json_data = json_data
        self.status_code = status_code
        self.headers = {"content-type": "text/html"}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("error", request=None, response=None)

    def json(self):
        return self._json_data


class FakeOnBaseClient:
    """Routes .get()/.post() calls the way the real OnBase flow expects:
    GET homepage -> HTML; POST InvokeDownload* -> JSON echoing DocumentName;
    GET ViewDocument -> PDF bytes."""

    def __init__(self, homepage_html=HOMEPAGE_HTML, pdf_bytes_by_filename=None, raise_on_invoke=False):
        self.homepage_html = homepage_html
        self.pdf_bytes_by_filename = pdf_bytes_by_filename or {}
        self.raise_on_invoke = raise_on_invoke
        self.requests = []

    def get(self, url):
        self.requests.append(("GET", url))
        if "ViewDocument" in url:
            name = urlparse(url).path.rsplit("/", 1)[-1]
            # Distinct content per filename by default, so multi-document
            # meetings don't collide on content-hash dedup.
            default_content = f"%PDF-1.4 fake content for {name}".encode()
            return FakeResponse(content=self.pdf_bytes_by_filename.get(name, default_content))
        return FakeResponse(content=self.homepage_html)

    def post(self, url, content=b""):
        self.requests.append(("POST", url))
        if self.raise_on_invoke:
            return FakeResponse(status_code=500)
        filename = url.rsplit("/", 1)[-1].split("?")[0]
        params = parse_qs(urlparse(url).query)
        return FakeResponse(
            json_data={
                "DocumentName": filename,
                "MeetingId": int(params.get("meetingId", [0])[0]),
                "ItemId": 0,
                "PublishId": 0,
                "IsSection": False,
            }
        )

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class TestParseMeetings:
    def test_parses_real_meeting_rows_with_documents(self):
        meetings = _parse_meetings(HOMEPAGE_HTML, "https://ecm.cityofsantacruz.com")

        assert len(meetings) == 2
        sister_cities = next(m for m in meetings if m["meeting_id"] == "2596")
        assert sister_cities["body"] == "Sister Cities"
        # 1783990800 is the real Unix timestamp captured live for this meeting --
        # 6:00 PM Pacific on 7/13/2026, i.e. 01:00 UTC the following day.
        assert sister_cities["start_time"].isoformat() == "2026-07-14T01:00:00+00:00"
        doc_types = {d["document_type"] for d in sister_cities["documents"]}
        assert doc_types == {"agenda", "packet"}

    def test_rows_with_no_document_links_are_skipped(self):
        meetings = _parse_meetings(HOMEPAGE_HTML, "https://ecm.cityofsantacruz.com")

        assert all(m["meeting_id"] != "9999" for m in meetings)

    def test_agenda_packet_is_flagged_as_attachment_agenda_is_not(self):
        meetings = _parse_meetings(HOMEPAGE_HTML, "https://ecm.cityofsantacruz.com")
        sister_cities = next(m for m in meetings if m["meeting_id"] == "2596")

        agenda = next(d for d in sister_cities["documents"] if d["document_type"] == "agenda")
        packet = next(d for d in sister_cities["documents"] if d["document_type"] == "packet")
        assert agenda["is_attachment"] is False
        assert packet["is_attachment"] is True

    def test_minutes_document_type_recognized(self):
        meetings = _parse_meetings(HOMEPAGE_HTML, "https://ecm.cityofsantacruz.com")
        city_council = next(m for m in meetings if m["meeting_id"] == "2578")

        assert city_council["documents"][0]["document_type"] == "minutes"

    def test_duplicate_rows_for_the_same_meeting_id_are_deduped(self):
        duplicated = HOMEPAGE_HTML + HOMEPAGE_HTML.replace(b"<table>", b"").replace(b"</table>", b"")
        meetings = _parse_meetings(duplicated, "https://ecm.cityofsantacruz.com")

        meeting_ids = [m["meeting_id"] for m in meetings]
        assert len(meeting_ids) == len(set(meeting_ids))

    def test_unknown_onbase_document_type_is_skipped(self):
        html = HOMEPAGE_HTML.replace(b"documentType=1&meetingId=2596", b"documentType=99&meetingId=2596")
        meetings = _parse_meetings(html, "https://ecm.cityofsantacruz.com")
        sister_cities = next(m for m in meetings if m["meeting_id"] == "2596")

        doc_types = {d["document_type"] for d in sister_cities["documents"]}
        assert doc_types == {"packet"}  # the agenda link's type=99 is unknown and dropped

    def test_row_missing_the_time_cell_is_skipped(self):
        html = b"""<table><tbody>
        <tr class="meeting-row" data-meeting-id="1">
        <td data-sortable-type="mtgType">Some Body</td>
        <td><a href="/OnBaseAgendaOnline/Documents/Downloadfile/x.pdf?documentType=1&meetingId=1"></a></td>
        </tr></tbody></table>"""
        assert _parse_meetings(html, "https://ecm.cityofsantacruz.com") == []

    def test_row_with_a_repeated_href_in_the_same_row_counts_it_once(self):
        html = b"""<table><tbody>
        <tr class="meeting-row" data-meeting-id="1">
        <td data-sortable-type="mtgType">Some Body</td>
        <td data-sortable-type="mtgTime" data-sortable-data="1768330800"></td>
        <td>
        <a href="/OnBaseAgendaOnline/Documents/Downloadfile/x.pdf?documentType=1&meetingId=1"></a>
        <a href="/OnBaseAgendaOnline/Documents/Downloadfile/x.pdf?documentType=1&meetingId=1"></a>
        </td>
        </tr></tbody></table>"""
        meetings = _parse_meetings(html, "https://ecm.cityofsantacruz.com")
        assert len(meetings[0]["documents"]) == 1


class TestResolvePdf:
    def test_non_attachment_uses_invoke_download_meeting_document(self):
        client = FakeOnBaseClient()
        doc = {"filename": "Agenda.pdf", "onbase_type": "1", "is_attachment": False}

        _resolve_pdf(client, "https://ecm.cityofsantacruz.com", "2596", doc)

        invoke_calls = [url for method, url in client.requests if method == "POST"]
        assert len(invoke_calls) == 1
        assert "InvokeDownloadMeetingDocument" in invoke_calls[0]
        assert "InvokeDownloadAttachment" not in invoke_calls[0]

    def test_attachment_uses_invoke_download_attachment(self):
        client = FakeOnBaseClient()
        doc = {"filename": "Packet.pdf", "onbase_type": "5", "is_attachment": True}

        _resolve_pdf(client, "https://ecm.cityofsantacruz.com", "2596", doc)

        invoke_calls = [url for method, url in client.requests if method == "POST"]
        assert "InvokeDownloadAttachment" in invoke_calls[0]

    def test_returns_the_view_document_response(self):
        client = FakeOnBaseClient(pdf_bytes_by_filename={})
        doc = {"filename": "Agenda.pdf", "onbase_type": "1", "is_attachment": False}

        response = _resolve_pdf(client, "https://ecm.cityofsantacruz.com", "2596", doc)

        assert response.content.startswith(b"%PDF")

    def test_raises_on_invoke_failure(self):
        client = FakeOnBaseClient(raise_on_invoke=True)
        doc = {"filename": "Agenda.pdf", "onbase_type": "1", "is_attachment": False}

        with pytest.raises(httpx.HTTPStatusError):
            _resolve_pdf(client, "https://ecm.cityofsantacruz.com", "2596", doc)


class TestIngestOnbaseAgenda:
    def _install(self, monkeypatch, **kwargs):
        fake_client = FakeOnBaseClient(**kwargs)
        monkeypatch.setattr(onbase_agenda_module.httpx, "Client", lambda **k: fake_client)
        return fake_client

    def test_creates_documents_and_links_meetings(self, db, archive_root, monkeypatch):
        source = make_source(
            db, name="OnBase", url="https://ecm.cityofsantacruz.com/OnBaseAgendaOnline/", fetch_method="onbase_agenda_online"
        )
        self._install(monkeypatch)

        created = ingest_onbase_agenda(db, source)

        assert created == 3  # agenda + packet for Sister Cities, minutes for City Council
        docs = db.query(Document).filter(Document.source_id == source.id).all()
        doc_types = sorted(d.document_type for d in docs)
        assert doc_types == ["agenda", "minutes", "packet", "source_page_snapshot"]

    def test_links_agenda_and_packet_to_the_same_meeting(self, db, archive_root, monkeypatch):
        source = make_source(
            db, name="OnBase", url="https://ecm.cityofsantacruz.com/OnBaseAgendaOnline/", fetch_method="onbase_agenda_online"
        )
        self._install(monkeypatch)

        ingest_onbase_agenda(db, source)

        meeting = db.query(Meeting).filter(Meeting.body == "Sister Cities").one()
        assert meeting.agenda_document_id is not None
        assert meeting.packet_document_id is not None

    def test_rerunning_dedupes_by_content_hash(self, db, archive_root, monkeypatch):
        source = make_source(
            db, name="OnBase", url="https://ecm.cityofsantacruz.com/OnBaseAgendaOnline/", fetch_method="onbase_agenda_online"
        )
        self._install(monkeypatch)

        first = ingest_onbase_agenda(db, source)
        second = ingest_onbase_agenda(db, source)

        assert first == 3
        assert second == 0

    def test_homepage_fetch_failure_is_recorded_and_does_not_crash(self, db, archive_root, monkeypatch):
        source = make_source(
            db, name="OnBase", url="https://ecm.cityofsantacruz.com/OnBaseAgendaOnline/", fetch_method="onbase_agenda_online"
        )

        class RaisingClient(FakeOnBaseClient):
            def get(self, url):
                raise httpx.ConnectError("connection refused")

        monkeypatch.setattr(onbase_agenda_module.httpx, "Client", lambda **k: RaisingClient())

        created = ingest_onbase_agenda(db, source)

        assert created == 0
        assert source.consecutive_failures == 1
        assert source.last_error is not None

    def test_document_resolution_failure_for_one_item_does_not_block_the_rest(self, db, archive_root, monkeypatch):
        source = make_source(
            db, name="OnBase", url="https://ecm.cityofsantacruz.com/OnBaseAgendaOnline/", fetch_method="onbase_agenda_online"
        )

        class FlakyClient(FakeOnBaseClient):
            def post(self, url, content=b""):
                if "meetingId=2596" in url:
                    raise httpx.ConnectError("connection refused")
                return super().post(url, content=content)

        monkeypatch.setattr(onbase_agenda_module.httpx, "Client", lambda **k: FlakyClient())

        created = ingest_onbase_agenda(db, source)

        assert created == 1  # only City Council's minutes made it through

    def test_homepage_parse_crash_is_caught_and_recorded_as_empty(self, db, archive_root, monkeypatch):
        source = make_source(
            db, name="OnBase", url="https://ecm.cityofsantacruz.com/OnBaseAgendaOnline/", fetch_method="onbase_agenda_online"
        )
        self._install(monkeypatch)
        monkeypatch.setattr(
            onbase_agenda_module,
            "_parse_meetings",
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
        )

        created = ingest_onbase_agenda(db, source)

        assert created == 0
        from app.models import Fetch

        fetch = db.query(Fetch).filter(Fetch.source_id == source.id).order_by(Fetch.fetched_at.desc()).first()
        assert fetch.validation_status == "empty"
