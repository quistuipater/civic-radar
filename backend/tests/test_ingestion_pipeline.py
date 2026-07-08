"""Tests for the document-ingestion pipeline: content-hash dedup, the
source_page_snapshot fast path (parser_status="skipped" so nothing wastes
time parsing/chunking text that's never read), and the connector-health
validation_status logic (ok/empty/error) mirroring what test_crime_data.py
covers for the structured-data side of ingestion.
"""

import httpx

import app.ingestion.pipeline as pipeline_module
from app.ingestion.connectors.base import DiscoveredDocument
from app.ingestion.pipeline import _upsert_document, ingest_source
from app.models import Document

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

        def broken_discover(html_bytes, base_url):
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
