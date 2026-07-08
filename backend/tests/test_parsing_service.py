"""Tests for the parse-document orchestration: writing extracted text,
(re)creating chunks, filling structured fields without clobbering existing
values, and the two failure-safety behaviors -- a parse exception marking
the document failed rather than crashing the worker, and the wall-clock
timeout for pathological documents.
"""

import time

import app.parsing.service as service_module
from app.models import DocumentChunk

from .conftest import make_document


class TestParseDocument:
    def test_already_parsed_document_is_a_no_op(self, db, tmp_path):
        document = make_document(db, parser_status="parsed", archive_path=str(tmp_path / "does-not-exist.txt"))
        db.commit()

        service_module.parse_document(db, document)  # would raise if it tried to read the (missing) file

        assert document.parser_status == "parsed"

    def test_successful_parse_writes_text_creates_chunks_and_marks_parsed(self, db, tmp_path):
        path = tmp_path / "notice.txt"
        path.write_text("This notice concerns Ordinance No. 2026-05.")
        document = make_document(db, archive_path=str(path), parser_status="pending")
        db.commit()

        service_module.parse_document(db, document)

        assert document.parser_status == "parsed"
        assert document.parser_error is None
        assert document.extracted_text_path == str(path.with_suffix(".txt.txt"))
        assert "Ordinance No. 2026-05" in open(document.extracted_text_path).read()
        chunks = db.query(DocumentChunk).filter_by(document_id=document.id).all()
        assert len(chunks) == 1

    def test_extracted_structured_fields_are_filled_in_when_not_already_set(self, db, tmp_path):
        path = tmp_path / "notice.txt"
        path.write_text("Case No. PL2026-0042 is under review.")
        document = make_document(db, archive_path=str(path), project_number=None)
        db.commit()

        service_module.parse_document(db, document)

        assert document.project_number == "PL2026-0042"

    def test_existing_structured_field_values_are_not_overwritten(self, db, tmp_path):
        path = tmp_path / "notice.txt"
        path.write_text("Case No. PL2026-9999 is under review.")
        document = make_document(db, archive_path=str(path), project_number="PL2026-0001-ALREADY-SET")
        db.commit()

        service_module.parse_document(db, document)

        assert document.project_number == "PL2026-0001-ALREADY-SET"

    def test_reparsing_replaces_old_chunks_rather_than_appending(self, db, tmp_path):
        path = tmp_path / "notice.txt"
        path.write_text("short text")
        document = make_document(db, archive_path=str(path), parser_status="pending")
        db.commit()

        service_module.parse_document(db, document)
        first_chunk_count = db.query(DocumentChunk).filter_by(document_id=document.id).count()

        document.parser_status = "pending"  # force a reparse
        service_module.parse_document(db, document)
        second_chunk_count = db.query(DocumentChunk).filter_by(document_id=document.id).count()

        assert first_chunk_count == second_chunk_count == 1

    def test_parse_failure_marks_document_failed_with_error_message(self, db, tmp_path):
        document = make_document(
            db, archive_path=str(tmp_path / "does-not-exist.zip"), parser_status="pending"
        )
        db.commit()

        service_module.parse_document(db, document)

        assert document.parser_status == "failed"
        assert document.parser_error is not None
        assert document.extracted_text_path is None

    def test_long_error_message_is_truncated_to_2000_chars(self, db, tmp_path, monkeypatch):
        document = make_document(db, archive_path=str(tmp_path / "doc.txt"), parser_status="pending")
        db.commit()

        def raise_long_error(path, mime_type):
            raise ValueError("x" * 5000)

        monkeypatch.setattr(service_module, "parse_file", raise_long_error)

        service_module.parse_document(db, document)

        assert document.parser_status == "failed"
        assert len(document.parser_error) == 2000

    def test_wall_clock_timeout_marks_document_failed_rather_than_hanging(self, db, tmp_path, monkeypatch):
        document = make_document(db, archive_path=str(tmp_path / "doc.txt"), parser_status="pending")
        db.commit()

        def slow_parse(path, mime_type):
            time.sleep(2)
            raise AssertionError("should have been interrupted by the alarm before reaching here")

        monkeypatch.setattr(service_module, "parse_file", slow_parse)
        monkeypatch.setattr(service_module, "PARSE_TIMEOUT_SECONDS", 1)

        service_module.parse_document(db, document)

        assert document.parser_status == "failed"
        assert "exceeded" in document.parser_error
