"""Tests for the document-ingestion pipeline: content-hash dedup, the
source_page_snapshot fast path (parser_status="skipped" so nothing wastes
time parsing/chunking text that's never read), and the connector-health
validation_status logic (ok/empty/error) mirroring what test_crime_data.py
covers for the structured-data side of ingestion.
"""

import httpx

from datetime import date, datetime, timedelta, timezone

import app.ingestion.pipeline as pipeline_module
from app.ingestion.connectors.base import DiscoveredDocument
from app.ingestion.pipeline import (
    _fetch_and_store_document,
    _link_meeting_document,
    _upsert_document,
    _upsert_meeting,
    ingest_source,
)
from app.models import Document, Fetch, Meeting

from .conftest import make_source


def fake_response(content: bytes, status_code: int = 200, content_type: str = "text/html") -> httpx.Response:
    return httpx.Response(status_code=status_code, content=content, headers={"content-type": content_type})


class TestUpsertDocument:
    def test_snapshot_documents_skip_the_parse_queue(self, db, archive_root):
        source = make_source(db)
        fetch = pipeline_module.Fetch(source_id=source.id, status="ok")
        db.add(fetch)
        db.flush()

        doc, is_new = _upsert_document(
            db,
            source=source,
            fetch=fetch,
            archive_path=archive_root / "snap.html",
            content=b"<html></html>",
            content_hash="hash1",
            document_type="source_page_snapshot",
            title="snapshot",
            original_url=source.url,
            mime_type="text/html",
            meeting_date=None,
            body_name=None,
        )

        assert is_new is True
        assert doc.parser_status == "skipped"

    def test_real_documents_go_into_the_parse_queue(self, db, archive_root):
        source = make_source(db)
        fetch = pipeline_module.Fetch(source_id=source.id, status="ok")
        db.add(fetch)
        db.flush()

        doc, is_new = _upsert_document(
            db,
            source=source,
            fetch=fetch,
            archive_path=archive_root / "agenda.pdf",
            content=b"%PDF-1.4",
            content_hash="hash2",
            document_type="agenda",
            title="June Agenda",
            original_url=source.url,
            mime_type="application/pdf",
            meeting_date=None,
            body_name=None,
        )

        assert is_new is True
        assert doc.parser_status == "pending"

    def test_same_content_hash_is_deduped_not_recreated(self, db, archive_root):
        source = make_source(db)
        fetch = pipeline_module.Fetch(source_id=source.id, status="ok")
        db.add(fetch)
        db.flush()
        kwargs = dict(
            source=source,
            fetch=fetch,
            archive_path=archive_root / "agenda.pdf",
            content=b"%PDF-1.4",
            content_hash="samehash",
            document_type="agenda",
            title="June Agenda",
            original_url=source.url,
            mime_type="application/pdf",
            meeting_date=None,
            body_name=None,
        )

        doc1, is_new1 = _upsert_document(db, **kwargs)
        doc2, is_new2 = _upsert_document(db, **kwargs)

        assert is_new1 is True
        assert is_new2 is False
        assert doc1.id == doc2.id
        assert db.query(Document).filter_by(source_id=source.id).count() == 1


class TestIngestSource:
    def test_page_with_no_discoverable_links_is_flagged_empty(self, db, archive_root, monkeypatch):
        source = make_source(db, connector="generic")
        monkeypatch.setattr(pipeline_module, "fetch_url", lambda url, **k: fake_response(b"<html><body>nothing here</body></html>"))

        fetch = ingest_source(db, source)

        assert fetch.status == "ok"
        assert fetch.items_found == 0
        assert fetch.validation_status == "empty"

    def test_page_with_links_is_flagged_ok_and_documents_are_archived(self, db, archive_root, monkeypatch):
        source = make_source(db, connector="generic")
        page_html = b'<html><body><a href="/notice.pdf">Public Notice</a></body></html>'

        def fake_fetch(url, **kwargs):
            if url == source.url:
                return fake_response(page_html)
            return fake_response(b"%PDF-1.4 fake pdf content", content_type="application/pdf")

        monkeypatch.setattr(pipeline_module, "fetch_url", fake_fetch)

        fetch = ingest_source(db, source)

        assert fetch.validation_status == "ok"
        assert fetch.items_found == 1
        assert fetch.changed is True
        docs = db.query(Document).filter_by(source_id=source.id, document_type="notice").all()
        assert len(docs) == 1

    def test_source_body_is_passed_through_to_the_connector(self, db, archive_root, monkeypatch):
        # Regression test for a live bug where the primegov connector ignored
        # the source's body and hardcoded "Board of Supervisors" for every
        # committee -- see tests/test_primegov.py for the connector-level fix.
        # This test guards the pipeline side: whatever body the connector
        # returns on a DiscoveredDocument must actually reach the Document row.
        source = make_source(db, connector="generic", body="Planning Commission")
        monkeypatch.setattr(pipeline_module, "fetch_url", lambda url, **k: fake_response(b"<html></html>"))

        seen_kwargs = {}

        def fake_discover(html_bytes, base_url, **kwargs):
            seen_kwargs.update(kwargs)
            return []

        monkeypatch.setitem(pipeline_module.CONNECTORS, "generic", fake_discover)

        ingest_source(db, source)

        assert seen_kwargs.get("source_body") == "Planning Commission"

    def test_http_failure_is_flagged_error_and_increments_failure_count(self, db, archive_root, monkeypatch):
        source = make_source(db)

        def raise_error(url, **kwargs):
            raise httpx.ConnectError("connection refused")

        monkeypatch.setattr(pipeline_module, "fetch_url", raise_error)

        fetch = ingest_source(db, source)

        assert fetch.status == "error"
        assert fetch.validation_status == "error"
        assert source.consecutive_failures == 1

    def test_connector_raising_is_flagged_error_but_snapshot_is_still_archived(self, db, archive_root, monkeypatch):
        source = make_source(db, connector="generic")
        monkeypatch.setattr(pipeline_module, "fetch_url", lambda url, **k: fake_response(b"<html></html>"))

        def broken_discover(html_bytes, base_url, **kwargs):
            raise ValueError("simulated connector bug")

        monkeypatch.setitem(pipeline_module.CONNECTORS, "generic", broken_discover)

        fetch = ingest_source(db, source)

        assert fetch.validation_status == "error"
        assert "simulated connector bug" in fetch.validation_message
        # The page snapshot itself should still have been archived even
        # though the connector crashed -- archive-first must not depend on
        # the connector succeeding.
        snapshots = db.query(Document).filter_by(source_id=source.id, document_type="source_page_snapshot").all()
        assert len(snapshots) == 1

    def test_rerunning_against_unchanged_page_does_not_recreate_snapshot(self, db, archive_root, monkeypatch):
        source = make_source(db, connector="generic")
        monkeypatch.setattr(pipeline_module, "fetch_url", lambda url, **k: fake_response(b"<html>same</html>"))

        ingest_source(db, source)
        second_fetch = ingest_source(db, source)

        assert second_fetch.changed is False
        assert db.query(Document).filter_by(source_id=source.id, document_type="source_page_snapshot").count() == 1

    def test_a_failed_document_download_is_skipped_not_fatal_to_the_rest_of_the_batch(self, db, archive_root, monkeypatch):
        source = make_source(db, connector="generic")
        page_html = (
            b'<html><body>'
            b'<a href="/broken.pdf">Broken</a>'
            b'<a href="/ok.pdf">OK</a>'
            b"</body></html>"
        )

        def fake_fetch(url, **kwargs):
            if url == source.url:
                return fake_response(page_html)
            if url.endswith("/broken.pdf"):
                raise httpx.ConnectError("connection refused")
            return fake_response(b"%PDF-1.4 ok content", content_type="application/pdf")

        monkeypatch.setattr(pipeline_module, "fetch_url", fake_fetch)

        fetch = ingest_source(db, source)

        assert fetch.validation_status == "ok"
        docs = db.query(Document).filter_by(source_id=source.id, document_type="pdf").all()
        assert len(docs) == 1


class TestFetchAndStoreDocument:
    def _make_fetch(self, db, source):
        f = Fetch(source_id=source.id, status="ok")
        db.add(f)
        db.flush()
        return f

    def test_duplicate_content_is_skipped(self, db, archive_root, monkeypatch):
        source = make_source(db)
        fetch = self._make_fetch(db, source)
        monkeypatch.setattr(pipeline_module, "fetch_url", lambda url, **k: fake_response(b"same content", content_type="application/pdf"))
        item = DiscoveredDocument(url="https://example.invalid/a.pdf", document_type="pdf")

        first = _fetch_and_store_document(db, source, fetch, item)
        second = _fetch_and_store_document(db, source, fetch, item)

        assert first is True
        assert second is False
        assert db.query(Document).filter_by(source_id=source.id).count() == 1

    def test_unknown_content_type_falls_back_to_url_extension(self, db, archive_root, monkeypatch):
        source = make_source(db)
        fetch = self._make_fetch(db, source)
        monkeypatch.setattr(
            pipeline_module, "fetch_url", lambda url, **k: fake_response(b"data", content_type="application/octet-stream")
        )
        item = DiscoveredDocument(url="https://example.invalid/report.csv", document_type="pdf")

        _fetch_and_store_document(db, source, fetch, item)

        doc = db.query(Document).filter_by(source_id=source.id).one()
        assert doc.archive_path.endswith(".csv")

    def test_unknown_content_type_and_no_url_extension_falls_back_to_bin(self, db, archive_root, monkeypatch):
        source = make_source(db)
        fetch = self._make_fetch(db, source)
        monkeypatch.setattr(
            pipeline_module, "fetch_url", lambda url, **k: fake_response(b"data", content_type="application/octet-stream")
        )
        item = DiscoveredDocument(url="https://example.invalid/download", document_type="pdf")

        _fetch_and_store_document(db, source, fetch, item)

        doc = db.query(Document).filter_by(source_id=source.id).one()
        assert doc.archive_path.endswith(".bin")

    def test_item_with_meeting_date_and_body_links_to_a_meeting(self, db, archive_root, monkeypatch):
        source = make_source(db, jurisdiction="City of Ventura")
        fetch = self._make_fetch(db, source)
        monkeypatch.setattr(pipeline_module, "fetch_url", lambda url, **k: fake_response(b"agenda content", content_type="application/pdf"))
        item = DiscoveredDocument(
            url="https://example.invalid/agenda.pdf",
            document_type="agenda",
            meeting_date=date(2026, 6, 1),
            body="City Council",
        )

        _fetch_and_store_document(db, source, fetch, item)

        meeting = db.query(Meeting).filter_by(jurisdiction="City of Ventura", body="City Council").one()
        doc = db.query(Document).filter_by(source_id=source.id).one()
        assert meeting.agenda_document_id == doc.id

    def test_item_missing_meeting_date_does_not_create_a_meeting(self, db, archive_root, monkeypatch):
        source = make_source(db)
        fetch = self._make_fetch(db, source)
        monkeypatch.setattr(pipeline_module, "fetch_url", lambda url, **k: fake_response(b"content", content_type="application/pdf"))
        item = DiscoveredDocument(url="https://example.invalid/a.pdf", document_type="agenda", meeting_date=None, body="City Council")

        _fetch_and_store_document(db, source, fetch, item)

        assert db.query(Meeting).count() == 0

    def test_item_missing_body_does_not_create_a_meeting(self, db, archive_root, monkeypatch):
        source = make_source(db)
        fetch = self._make_fetch(db, source)
        monkeypatch.setattr(pipeline_module, "fetch_url", lambda url, **k: fake_response(b"content", content_type="application/pdf"))
        item = DiscoveredDocument(url="https://example.invalid/a.pdf", document_type="agenda", meeting_date=date(2026, 6, 1), body=None)

        _fetch_and_store_document(db, source, fetch, item)

        assert db.query(Meeting).count() == 0


class TestUpsertMeeting:
    def test_creates_a_new_meeting_when_none_exists(self, db):
        source = make_source(db, jurisdiction="City of Ventura", agency="City Clerk")
        item = DiscoveredDocument(
            url="https://example.invalid/a.pdf",
            document_type="agenda",
            meeting_date=date(2026, 6, 1),
            body="City Council",
            meeting_type="Regular Meeting",
        )

        meeting = _upsert_meeting(db, source, item)

        assert meeting.jurisdiction == "City of Ventura"
        assert meeting.agency == "City Clerk"
        assert meeting.body == "City Council"
        assert meeting.meeting_type == "Regular Meeting"

    def test_agency_falls_back_to_jurisdiction_when_source_has_none(self, db):
        source = make_source(db, jurisdiction="City of Ventura", agency=None)
        item = DiscoveredDocument(url="https://example.invalid/a.pdf", document_type="agenda", meeting_date=date(2026, 6, 1), body="City Council")

        meeting = _upsert_meeting(db, source, item)

        assert meeting.agency == "City of Ventura"

    def test_reuses_existing_meeting_matching_jurisdiction_body_and_date(self, db):
        source = make_source(db, jurisdiction="City of Ventura")
        item = DiscoveredDocument(url="https://example.invalid/a.pdf", document_type="agenda", meeting_date=date(2026, 6, 1), body="City Council")

        first = _upsert_meeting(db, source, item)
        second = _upsert_meeting(db, source, item)

        assert first.id == second.id
        assert db.query(Meeting).count() == 1

    def test_future_meeting_date_is_marked_scheduled(self, db):
        source = make_source(db)
        future_date = (datetime.now(timezone.utc) + timedelta(days=10)).date()
        item = DiscoveredDocument(url="https://example.invalid/a.pdf", document_type="agenda", meeting_date=future_date, body="City Council")

        meeting = _upsert_meeting(db, source, item)

        assert meeting.status == "scheduled"

    def test_past_meeting_date_is_marked_completed(self, db):
        source = make_source(db)
        past_date = (datetime.now(timezone.utc) - timedelta(days=10)).date()
        item = DiscoveredDocument(url="https://example.invalid/a.pdf", document_type="agenda", meeting_date=past_date, body="City Council")

        meeting = _upsert_meeting(db, source, item)

        assert meeting.status == "completed"


class TestLinkMeetingDocument:
    def test_links_agenda_document_type(self, db):
        source = make_source(db)
        meeting = Meeting(jurisdiction=source.jurisdiction, agency="City Clerk", body="City Council")
        db.add(meeting)
        document = Document(source_id=source.id, archive_path="/a.pdf", content_hash="h1")
        db.add(document)
        db.flush()

        _link_meeting_document(meeting, document, "agenda")

        assert meeting.agenda_document_id == document.id

    def test_links_packet_and_minutes_document_types_to_their_own_fields(self, db):
        source = make_source(db)
        meeting = Meeting(jurisdiction=source.jurisdiction, agency="City Clerk", body="City Council")
        db.add(meeting)
        packet_doc = Document(source_id=source.id, archive_path="/p.pdf", content_hash="h2")
        minutes_doc = Document(source_id=source.id, archive_path="/m.pdf", content_hash="h3")
        db.add_all([packet_doc, minutes_doc])
        db.flush()

        _link_meeting_document(meeting, packet_doc, "packet")
        _link_meeting_document(meeting, minutes_doc, "minutes")

        assert meeting.packet_document_id == packet_doc.id
        assert meeting.minutes_document_id == minutes_doc.id

    def test_unrecognized_document_type_is_a_no_op(self, db):
        source = make_source(db)
        meeting = Meeting(jurisdiction=source.jurisdiction, agency="City Clerk", body="City Council")
        db.add(meeting)
        document = Document(source_id=source.id, archive_path="/n.pdf", content_hash="h4")
        db.add(document)
        db.flush()

        _link_meeting_document(meeting, document, "notice")

        assert meeting.agenda_document_id is None
        assert meeting.packet_document_id is None
        assert meeting.minutes_document_id is None

    def test_does_not_overwrite_an_already_linked_field(self, db):
        source = make_source(db)
        meeting = Meeting(jurisdiction=source.jurisdiction, agency="City Clerk", body="City Council")
        db.add(meeting)
        first_doc = Document(source_id=source.id, archive_path="/first.pdf", content_hash="h5")
        second_doc = Document(source_id=source.id, archive_path="/second.pdf", content_hash="h6")
        db.add_all([first_doc, second_doc])
        db.flush()

        _link_meeting_document(meeting, first_doc, "agenda")
        _link_meeting_document(meeting, second_doc, "agenda")

        assert meeting.agenda_document_id == first_doc.id
