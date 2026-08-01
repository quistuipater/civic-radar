"""Tests for DbLogHandler (mirrors ERROR+ log records into app_logs) and
prune_app_logs (30-day retention). DbLogHandler opens its own session via
a session_factory rather than taking a db param -- same reasoning as
worker.py's SessionLocal usage (see conftest.py's db_session_factory
docstring) -- so tests inject db_session_factory to keep writes inside the
isolated test transaction.
"""

import logging
import sys
import uuid
from datetime import timedelta

from app.log_handler import DbLogHandler, prune_app_logs
from app.models import AppLog

from .conftest import make_app_log, make_source, utcnow


class TestDbLogHandlerEmit:
    def test_writes_a_row_with_level_logger_name_and_message(self, db, db_session_factory):
        handler = DbLogHandler(db_session_factory)
        logger = logging.getLogger("test.log_handler.basic")
        logger.addHandler(handler)
        logger.propagate = False
        try:
            logger.error("boom")
        finally:
            logger.removeHandler(handler)

        row = db.query(AppLog).one()
        assert row.level == "ERROR"
        assert row.logger_name == "test.log_handler.basic"
        assert row.message == "boom"
        assert row.traceback is None
        assert row.source_id is None

    def test_formats_message_args(self, db, db_session_factory):
        handler = DbLogHandler(db_session_factory)
        logger = logging.getLogger("test.log_handler.args")
        logger.addHandler(handler)
        logger.propagate = False
        try:
            logger.error("crashed for source %s", "Test Source")
        finally:
            logger.removeHandler(handler)

        row = db.query(AppLog).one()
        assert row.message == "crashed for source Test Source"

    def test_captures_traceback_when_exc_info_present(self, db, db_session_factory):
        handler = DbLogHandler(db_session_factory)
        logger = logging.getLogger("test.log_handler.exc")
        logger.addHandler(handler)
        logger.propagate = False
        try:
            try:
                raise ValueError("kaboom")
            except ValueError:
                logger.exception("it broke")
        finally:
            logger.removeHandler(handler)

        row = db.query(AppLog).one()
        assert row.message == "it broke"
        assert "ValueError: kaboom" in row.traceback

    def test_captures_source_id_from_extra(self, db, db_session_factory):
        handler = DbLogHandler(db_session_factory)
        logger = logging.getLogger("test.log_handler.source")
        logger.addHandler(handler)
        logger.propagate = False
        source = make_source(db)
        db.commit()
        try:
            logger.error("scoped error", extra={"source_id": source.id})
        finally:
            logger.removeHandler(handler)

        row = db.query(AppLog).one()
        assert row.source_id == source.id

    def test_db_failure_inside_emit_does_not_raise(self, capsys):
        def broken_factory():
            raise RuntimeError("db is down")

        handler = DbLogHandler(broken_factory)
        logger = logging.getLogger("test.log_handler.dbfail")
        logger.addHandler(handler)
        logger.propagate = False
        try:
            logger.error("this must not raise")  # would raise if emit() didn't catch
        finally:
            logger.removeHandler(handler)

        captured = capsys.readouterr()
        assert "db is down" in captured.err


class TestPruneAppLogs:
    def test_deletes_rows_older_than_cutoff_and_keeps_recent(self, db):
        cutoff = utcnow() - timedelta(days=30)
        make_app_log(db, message="old", created_at=utcnow() - timedelta(days=31))
        make_app_log(db, message="recent", created_at=utcnow() - timedelta(days=1))
        db.commit()

        deleted = prune_app_logs(db, cutoff=cutoff)

        assert deleted == 1
        remaining = [row.message for row in db.query(AppLog).all()]
        assert remaining == ["recent"]

    def test_default_cutoff_is_30_days(self, db):
        make_app_log(db, message="just_over", created_at=utcnow() - timedelta(days=31))
        make_app_log(db, message="just_under", created_at=utcnow() - timedelta(days=29))
        db.commit()

        prune_app_logs(db)

        remaining = [row.message for row in db.query(AppLog).all()]
        assert remaining == ["just_under"]
