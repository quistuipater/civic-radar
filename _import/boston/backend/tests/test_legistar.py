"""Tests for the Boston Legistar ingestion module. Event shapes here are
copied from what was captured live against webapi.legistar.com on
2026-07-10 (see the module docstring) -- these tests pin down the
parsing/download logic against that shape, not against Legistar itself.
"""

import httpx
import pytest

import app.ingestion.legistar as legistar_module
from app.ingestion.legistar import _events_url, _parse_events, ingest_legistar
from app.models import Document, Meeting

from .conftest import make_source

REAL_EVENTS = [
    {
        "EventId": 3990,
        "EventBodyName": "City Council",
        "EventDate": "2025-10-01T00:00:00",
        "EventAgendaFile": "https://boston.legistar1.com/boston/meetings/2025/10/3990_A_City_Council_25-10-01_Meeting_Agenda.pdf",
        "EventMinutesFile": "https://boston.legistar1.com/boston/meetings/2025/10/3990_M_City_Council_25-10-01_Meeting_Minutes.pdf",
    },
    {
        "EventId": 4001,
        "EventBodyName": "City Council",
        "EventDate": "2025-10-08T00:00:00",
        "EventAgendaFile": "https://boston.legistar1.com/boston/meetings/2025/10/4001_A_City_Council_25-10-08_Meeting_Agenda.pdf",
        "EventMinutesFile": None,
    },
    {
        # Future meeting with no agenda posted yet -- no usable document links.
        "EventId": 4100,
        "EventBodyName": "City Council",
        "EventDate": "2026-12-16T00:00:00",
        "EventAgendaFile": None,
        "EventMinutesFile": None,
    },
    {
        # Malformed date -- should be skipped rather than crash the whole poll.
        "EventId": 4200,
        "EventBodyName": "City Council",
        "EventDate": "not-a-date",
        "EventAgendaFile": "https://boston.legistar1.com/boston/meetings/x.pdf",
        "EventMinutesFile": None,
    },
]


class FakeResponse:
    def __init__(self, content=b"", json_data=None, status_code=200):
        self.content = content
        self._json_data = json_data
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("error", request=None, response=None)

    def json(self):
        return self._json_data


class FakeLegistarClient:
    """Routes .get() the way the real flow expects: GET Events -> JSON;
    GET any *.pdf URL -> PDF bytes."""

    def __init__(self, events=REAL_EVENTS, pdf_bytes_by_url=None, raise_on_events=False):
        self.events = events
        self.pdf_bytes_by_url = pdf_bytes_by_url or {}
        self.raise_on_events = raise_on_events
        self.requests = []

    def get(self, url):
        self.requests.append(url)
        if url.endswith(".pdf"):
            default_content = f"%PDF-1.4 fake content for {url}".encode()
            return FakeResponse(content=self.pdf_bytes_by_url.get(url, default_content))
        if self.raise_on_events:
            raise httpx.ConnectError("connection refused")
        return FakeResponse(json_data=self.events)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class TestEventsUrl:
    def test_builds_body_and_date_scoped_odata_filter(self):
        url = _events_url("https://webapi.legistar.com/v1/boston/Events?bodyId=138")
        assert url.startswith("https://webapi.legistar.com/v1/boston/Events?$filter=")
        assert "EventBodyId eq 138" in url
        assert "EventDate ge datetime'" in url


class TestParseEvents:
    def test_parses_events_with_at_least_one_document(self):
        rows = _parse_events(REAL_EVENTS)
        event_ids = {r["event_id"] for r in rows}
        assert event_ids == {3990, 4001}

    def test_events_with_no_document_links_are_skipped(self):
        rows = _parse_events(REAL_EVENTS)
        assert all(r["event_id"] != 4100 for r in rows)

    def test_events_with_unparseable_dates_are_skipped(self):
        rows = _parse_events(REAL_EVENTS)
        assert all(r["event_id"] != 4200 for r in rows)

    def test_agenda_and_minutes_both_captured_when_present(self):
        rows = _parse_events(REAL_EVENTS)
        first = next(r for r in rows if r["event_id"] == 3990)
        doc_types = {d["document_type"] for d in first["documents"]}
        assert doc_types == {"agenda", "minutes"}

    def test_event_with_only_agenda_omits_minutes(self):
        rows = _parse_events(REAL_EVENTS)
        second = next(r for r in rows if r["event_id"] == 4001)
        doc_types = {d["document_type"] for d in second["documents"]}
        assert doc_types == {"agenda"}


class TestIngestLegistar:
    def _install(self, monkeypatch, **kwargs):
        fake_client = FakeLegistarClient(**kwargs)
        monkeypatch.setattr(legistar_module.httpx, "Client", lambda **k: fake_client)
        return fake_client

    def test_creates_documents_and_links_meetings(self, db, archive_root, monkeypatch):
        source = make_source(
            db, name="Legistar", url="https://webapi.legistar.com/v1/boston/Events?bodyId=138", fetch_method="legistar_api"
        )
        self._install(monkeypatch)

        created = ingest_legistar(db, source)

        assert created == 3  # agenda+minutes for 3990, agenda for 4001
        docs = db.query(Document).filter(Document.source_id == source.id).all()
        doc_types = sorted(d.document_type for d in docs)
        assert doc_types == ["agenda", "agenda", "minutes"]

    def test_links_agenda_and_minutes_to_the_same_meeting(self, db, archive_root, monkeypatch):
        source = make_source(
            db, name="Legistar", url="https://webapi.legistar.com/v1/boston/Events?bodyId=138", fetch_method="legistar_api"
        )
        self._install(monkeypatch)

        ingest_legistar(db, source)

        meeting = db.query(Meeting).filter(Meeting.body == "City Council", Meeting.start_time.isnot(None)).all()
        linked = next(m for m in meeting if m.minutes_document_id is not None)
        assert linked.agenda_document_id is not None

    def test_rerunning_dedupes_by_content_hash(self, db, archive_root, monkeypatch):
        source = make_source(
            db, name="Legistar", url="https://webapi.legistar.com/v1/boston/Events?bodyId=138", fetch_method="legistar_api"
        )
        self._install(monkeypatch)

        first = ingest_legistar(db, source)
        second = ingest_legistar(db, source)

        assert first == 3
        assert second == 0

    def test_events_fetch_failure_is_recorded_and_does_not_crash(self, db, archive_root, monkeypatch):
        source = make_source(
            db, name="Legistar", url="https://webapi.legistar.com/v1/boston/Events?bodyId=138", fetch_method="legistar_api"
        )
        self._install(monkeypatch, raise_on_events=True)

        created = ingest_legistar(db, source)

        assert created == 0
        assert source.consecutive_failures == 1
        assert source.last_error is not None

    def test_document_download_failure_for_one_item_does_not_block_the_rest(self, db, archive_root, monkeypatch):
        source = make_source(
            db, name="Legistar", url="https://webapi.legistar.com/v1/boston/Events?bodyId=138", fetch_method="legistar_api"
        )

        class FlakyClient(FakeLegistarClient):
            def get(self, url):
                if "3990_A_City_Council" in url:
                    raise httpx.ConnectError("connection refused")
                return super().get(url)

        monkeypatch.setattr(legistar_module.httpx, "Client", lambda **k: FlakyClient())

        created = ingest_legistar(db, source)

        assert created == 2  # 3990's minutes + 4001's agenda still succeed

    def test_no_events_returned_is_recorded_as_empty(self, db, archive_root, monkeypatch):
        source = make_source(
            db, name="Legistar", url="https://webapi.legistar.com/v1/boston/Events?bodyId=138", fetch_method="legistar_api"
        )
        self._install(monkeypatch, events=[])

        created = ingest_legistar(db, source)

        assert created == 0
        from app.models import Fetch

        fetch = db.query(Fetch).filter(Fetch.source_id == source.id).one()
        assert fetch.validation_status == "empty"
