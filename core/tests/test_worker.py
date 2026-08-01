"""Tests for the scheduler loop. worker.py's run_*() functions each open
their own SessionLocal() rather than taking a `db` parameter, so SessionLocal
is monkeypatched to the test's db_session_factory (sharing the same
isolated connection/transaction as the `db` fixture) rather than hitting the
real civic_radar database. ingest_source/ingest_crime_source/parse_document/
run_ai_pipeline/match_document_to_issue/create_alert_from_classification are
all treated as spies -- each has its own dedicated tests elsewhere; this
module's job is the scheduling/batching/crash-isolation logic around them.
"""

import logging
from datetime import datetime, timedelta, timezone

import pytest

import app.worker as worker_module
from app.archive import now_utc
from app.models import Document

from .conftest import make_ai_output, make_document, make_source


class TestIsDue:
    def test_never_fetched_is_due(self):
        source = worker_module.Source(last_fetched_at=None, polling_interval_minutes=240)
        assert worker_module.is_due(source, now_utc()) is True

    def test_not_due_when_interval_has_not_elapsed(self):
        now = now_utc()
        source = worker_module.Source(last_fetched_at=now - timedelta(minutes=10), polling_interval_minutes=240)
        assert worker_module.is_due(source, now) is False

    def test_due_when_interval_has_elapsed(self):
        now = now_utc()
        source = worker_module.Source(last_fetched_at=now - timedelta(minutes=300), polling_interval_minutes=240)
        assert worker_module.is_due(source, now) is True

    def test_due_at_the_exact_interval_boundary(self):
        now = now_utc()
        source = worker_module.Source(last_fetched_at=now - timedelta(minutes=240), polling_interval_minutes=240)
        assert worker_module.is_due(source, now) is True

    def test_defaults_to_240_minutes_when_interval_is_none(self):
        now = now_utc()
        source = worker_module.Source(last_fetched_at=now - timedelta(minutes=241), polling_interval_minutes=None)
        assert worker_module.is_due(source, now) is True
        source2 = worker_module.Source(last_fetched_at=now - timedelta(minutes=100), polling_interval_minutes=None)
        assert worker_module.is_due(source2, now) is False


class TestRunIngestionTick:
    def test_disabled_sources_are_not_ingested(self, db, db_session_factory, monkeypatch):
        monkeypatch.setattr(worker_module, "SessionLocal", db_session_factory)
        calls = []
        monkeypatch.setattr(worker_module, "ingest_source", lambda db, s: calls.append(s.name))
        make_source(db, name="Disabled Source", enabled=False)
        db.commit()

        worker_module.run_ingestion_tick()

        assert calls == []

    def test_not_yet_due_sources_are_skipped(self, db, db_session_factory, monkeypatch):
        monkeypatch.setattr(worker_module, "SessionLocal", db_session_factory)
        calls = []
        monkeypatch.setattr(worker_module, "ingest_source", lambda db, s: calls.append(s.name))
        make_source(db, name="Recently Fetched", last_fetched_at=now_utc(), polling_interval_minutes=240)
        db.commit()

        worker_module.run_ingestion_tick()

        assert calls == []

    def test_due_sources_are_ingested(self, db, db_session_factory, monkeypatch):
        monkeypatch.setattr(worker_module, "SessionLocal", db_session_factory)
        calls = []
        monkeypatch.setattr(worker_module, "ingest_source", lambda db, s: calls.append(s.name))
        make_source(db, name="Never Fetched", last_fetched_at=None)
        db.commit()

        worker_module.run_ingestion_tick()

        assert calls == ["Never Fetched"]

    def test_crime_data_sources_are_routed_to_ingest_crime_source(self, db, db_session_factory, monkeypatch):
        monkeypatch.setattr(worker_module, "SessionLocal", db_session_factory)
        regular_calls, crime_calls = [], []
        monkeypatch.setattr(worker_module, "ingest_source", lambda db, s: regular_calls.append(s.name))
        monkeypatch.setattr(worker_module, "ingest_crime_source", lambda db, s: crime_calls.append(s.name))
        make_source(db, name="Crime Feed", fetch_method="arcgis_feature_query", last_fetched_at=None)
        db.commit()

        worker_module.run_ingestion_tick()

        assert crime_calls == ["Crime Feed"]
        assert regular_calls == []

    def test_one_sources_crash_does_not_stop_the_others(self, db, db_session_factory, monkeypatch):
        monkeypatch.setattr(worker_module, "SessionLocal", db_session_factory)
        calls = []

        def maybe_crash(db, s):
            if s.name == "Broken Source":
                raise RuntimeError("simulated ingestion crash")
            calls.append(s.name)

        monkeypatch.setattr(worker_module, "ingest_source", maybe_crash)
        make_source(db, name="Broken Source", last_fetched_at=None)
        make_source(db, name="Healthy Source", last_fetched_at=None)
        db.commit()

        worker_module.run_ingestion_tick()  # must not raise

        assert calls == ["Healthy Source"]


class TestRunParsingBatch:
    def test_only_pending_documents_are_parsed(self, db, db_session_factory, monkeypatch):
        monkeypatch.setattr(worker_module, "SessionLocal", db_session_factory)
        calls = []
        monkeypatch.setattr(worker_module, "parse_document", lambda db, d: calls.append(d.title))
        make_document(db, title="Pending Doc", parser_status="pending")
        make_document(db, title="Already Parsed", parser_status="parsed")
        db.commit()

        worker_module.run_parsing_batch()

        assert calls == ["Pending Doc"]

    def test_batch_size_is_respected(self, db, db_session_factory, monkeypatch):
        monkeypatch.setattr(worker_module, "SessionLocal", db_session_factory)
        monkeypatch.setattr(worker_module, "BATCH_SIZE", 2)
        calls = []
        monkeypatch.setattr(worker_module, "parse_document", lambda db, d: calls.append(d.id))
        for i in range(5):
            make_document(db, parser_status="pending", content_hash=f"hash-{i}")
        db.commit()

        worker_module.run_parsing_batch()

        assert len(calls) == 2

    def test_one_documents_crash_does_not_stop_the_batch(self, db, db_session_factory, monkeypatch):
        monkeypatch.setattr(worker_module, "SessionLocal", db_session_factory)
        calls = []

        def maybe_crash(db, d):
            if d.title == "Broken Doc":
                raise RuntimeError("simulated parse crash")
            calls.append(d.title)

        monkeypatch.setattr(worker_module, "parse_document", maybe_crash)
        make_document(db, title="Broken Doc", parser_status="pending", content_hash="h1")
        make_document(db, title="Healthy Doc", parser_status="pending", content_hash="h2")
        db.commit()

        worker_module.run_parsing_batch()  # must not raise

        assert calls == ["Healthy Doc"]


class TestRunAiBatch:
    def test_only_parsed_classifiable_unclassified_documents_are_processed(self, db, db_session_factory, monkeypatch):
        monkeypatch.setattr(worker_module, "SessionLocal", db_session_factory)
        calls = []
        monkeypatch.setattr(worker_module, "run_ai_pipeline", lambda db, d: calls.append(d.title))
        monkeypatch.setattr(worker_module, "match_document_to_issue", lambda db, d: None)

        make_document(db, title="Not Parsed Yet", parser_status="pending", document_type="agenda")
        make_document(db, title="Wrong Type", parser_status="parsed", document_type="source_page_snapshot")
        make_document(db, title="Ready To Classify", parser_status="parsed", document_type="agenda")
        db.commit()

        worker_module.run_ai_batch()

        assert calls == ["Ready To Classify"]

    def test_already_classified_documents_are_skipped(self, db, db_session_factory, monkeypatch):
        monkeypatch.setattr(worker_module, "SessionLocal", db_session_factory)
        calls = []
        monkeypatch.setattr(worker_module, "run_ai_pipeline", lambda db, d: calls.append(d.id))
        monkeypatch.setattr(worker_module, "match_document_to_issue", lambda db, d: None)

        document = make_document(db, parser_status="parsed", document_type="agenda")
        make_ai_output(db, document.id, task_type="classification")
        db.commit()

        worker_module.run_ai_batch()

        assert calls == []

    def test_creates_an_alert_when_classification_produced_output(self, db, db_session_factory, monkeypatch):
        monkeypatch.setattr(worker_module, "SessionLocal", db_session_factory)
        alert_calls = []

        def fake_pipeline(db, document):
            make_ai_output(db, document.id, task_type="classification", output_json={"importance_score": 5})

        monkeypatch.setattr(worker_module, "run_ai_pipeline", fake_pipeline)
        monkeypatch.setattr(worker_module, "match_document_to_issue", lambda db, d: None)
        monkeypatch.setattr(
            worker_module,
            "create_alert_from_classification",
            lambda db, document, ai_output, issue: alert_calls.append(document.id),
        )

        document = make_document(db, parser_status="parsed", document_type="agenda")
        db.commit()

        worker_module.run_ai_batch()

        assert alert_calls == [document.id]

    def test_no_alert_created_when_classification_produced_no_output(self, db, db_session_factory, monkeypatch):
        monkeypatch.setattr(worker_module, "SessionLocal", db_session_factory)
        alert_calls = []

        def fake_pipeline(db, document):
            make_ai_output(db, document.id, task_type="classification", output_json=None)

        monkeypatch.setattr(worker_module, "run_ai_pipeline", fake_pipeline)
        monkeypatch.setattr(worker_module, "match_document_to_issue", lambda db, d: None)
        monkeypatch.setattr(
            worker_module,
            "create_alert_from_classification",
            lambda db, document, ai_output, issue: alert_calls.append(document.id),
        )

        document = make_document(db, parser_status="parsed", document_type="agenda")
        db.commit()

        worker_module.run_ai_batch()

        assert alert_calls == []

    def test_one_documents_crash_does_not_stop_the_batch(self, db, db_session_factory, monkeypatch):
        monkeypatch.setattr(worker_module, "SessionLocal", db_session_factory)
        calls = []

        def maybe_crash(db, d):
            if d.title == "Broken Doc":
                raise RuntimeError("simulated AI crash")
            calls.append(d.title)

        monkeypatch.setattr(worker_module, "run_ai_pipeline", maybe_crash)
        monkeypatch.setattr(worker_module, "match_document_to_issue", lambda db, d: None)
        make_document(db, title="Broken Doc", parser_status="parsed", document_type="agenda")
        make_document(db, title="Healthy Doc", parser_status="parsed", document_type="agenda")
        db.commit()

        worker_module.run_ai_batch()  # must not raise

        assert calls == ["Healthy Doc"]


class TestTick:
    def test_runs_all_three_batches_in_order(self, db_session_factory, monkeypatch):
        monkeypatch.setattr(worker_module, "SessionLocal", db_session_factory)
        calls = []
        monkeypatch.setattr(worker_module, "run_ingestion_tick", lambda: calls.append("ingestion"))
        monkeypatch.setattr(worker_module, "run_parsing_batch", lambda: calls.append("parsing"))
        monkeypatch.setattr(worker_module, "run_ai_batch", lambda: calls.append("ai"))

        worker_module.tick()

        assert calls == ["ingestion", "parsing", "ai"]


class StopLoop(Exception):
    pass


class TestMain:
    @pytest.fixture(autouse=True)
    def _reset_root_log_handlers(self):
        # main() now attaches a real DbLogHandler to the root logger (Task
        # 2). That's a process-lifetime side effect in production (main()
        # runs once), but these tests call main() directly and repeatedly
        # within the same test process, so without cleanup each call would
        # leak another handler onto the shared root logger and pollute
        # later tests (e.g. test_main.py's handler-count assertion).
        root = logging.getLogger()
        original_handlers = list(root.handlers)
        yield
        root.handlers = original_handlers

    def test_loops_calling_tick_then_sleeping(self, monkeypatch):
        tick_calls = []
        monkeypatch.setattr(worker_module, "tick", lambda: tick_calls.append(1))

        def fake_sleep(seconds):
            raise StopLoop()

        monkeypatch.setattr(worker_module.time, "sleep", fake_sleep)

        try:
            worker_module.main()
        except StopLoop:
            pass

        assert tick_calls == [1]

    def test_a_crashing_tick_does_not_stop_the_loop(self, monkeypatch):
        def crash():
            raise RuntimeError("simulated tick crash")

        monkeypatch.setattr(worker_module, "tick", crash)

        def fake_sleep(seconds):
            raise StopLoop()

        monkeypatch.setattr(worker_module.time, "sleep", fake_sleep)

        try:
            worker_module.main()  # must reach time.sleep despite tick() raising
        except StopLoop:
            pass
        else:
            assert False, "expected StopLoop to propagate past main()'s except Exception"


class TestSourceIdOnCrashLogs:
    """The 3 crash sites in worker.py tag their logger.exception() calls with
    extra={"source_id": ...} so those specific errors are filterable by
    source in the Logs tab. Verified via caplog rather than DbLogHandler --
    this only needs to confirm the LogRecord carries the right extra field,
    independent of how it's eventually persisted.
    """

    def test_ingestion_crash_is_tagged_with_source_id(self, db, db_session_factory, monkeypatch, caplog):
        monkeypatch.setattr(worker_module, "SessionLocal", db_session_factory)

        def boom(db, source):
            raise RuntimeError("ingest failed")

        monkeypatch.setattr(worker_module, "ingest_source", boom)
        source = make_source(db, name="Boom Source")
        db.commit()

        with caplog.at_level(logging.ERROR):
            worker_module.run_ingestion_tick()

        [record] = [r for r in caplog.records if "ingestion crashed" in r.getMessage()]
        assert record.source_id == source.id

    def test_parsing_crash_is_tagged_with_document_source_id(self, db, db_session_factory, monkeypatch, caplog):
        monkeypatch.setattr(worker_module, "SessionLocal", db_session_factory)
        source = make_source(db)
        document = make_document(db, source=source, parser_status="pending")
        db.commit()

        def boom(db, doc):
            raise RuntimeError("parse failed")

        monkeypatch.setattr(worker_module, "parse_document", boom)

        with caplog.at_level(logging.ERROR):
            worker_module.run_parsing_batch()

        [record] = [r for r in caplog.records if "parsing crashed" in r.getMessage()]
        assert record.source_id == source.id

    def test_ai_pipeline_crash_is_tagged_with_document_source_id(self, db, db_session_factory, monkeypatch, caplog):
        monkeypatch.setattr(worker_module, "SessionLocal", db_session_factory)
        source = make_source(db)
        document = make_document(db, source=source, parser_status="parsed", document_type="agenda")
        db.commit()

        def boom(db, doc):
            raise RuntimeError("ai failed")

        monkeypatch.setattr(worker_module, "run_ai_pipeline", boom)

        with caplog.at_level(logging.ERROR):
            worker_module.run_ai_batch()

        [record] = [r for r in caplog.records if "AI pipeline crashed" in r.getMessage()]
        assert record.source_id == source.id


class TestMaybePruneAppLogs:
    def test_prunes_on_first_call(self, db_session_factory, monkeypatch):
        monkeypatch.setattr(worker_module, "SessionLocal", db_session_factory)
        monkeypatch.setattr(worker_module, "_last_prune_at", None)
        calls = []
        monkeypatch.setattr(worker_module, "prune_app_logs", lambda db: calls.append(1))

        worker_module.maybe_prune_app_logs()

        assert calls == [1]

    def test_skips_second_call_within_interval(self, db_session_factory, monkeypatch):
        monkeypatch.setattr(worker_module, "SessionLocal", db_session_factory)
        monkeypatch.setattr(worker_module, "_last_prune_at", None)
        calls = []
        monkeypatch.setattr(worker_module, "prune_app_logs", lambda db: calls.append(1))

        worker_module.maybe_prune_app_logs()
        worker_module.maybe_prune_app_logs()

        assert calls == [1]

    def test_prunes_again_after_interval_elapses(self, db_session_factory, monkeypatch):
        monkeypatch.setattr(worker_module, "SessionLocal", db_session_factory)
        monkeypatch.setattr(
            worker_module, "_last_prune_at", datetime.now(timezone.utc) - timedelta(days=2)
        )
        calls = []
        monkeypatch.setattr(worker_module, "prune_app_logs", lambda db: calls.append(1))

        worker_module.maybe_prune_app_logs()

        assert calls == [1]


class TestTickPrunesAppLogs:
    def test_tick_calls_maybe_prune_app_logs(self, db, db_session_factory, monkeypatch):
        monkeypatch.setattr(worker_module, "SessionLocal", db_session_factory)
        monkeypatch.setattr(worker_module, "run_ingestion_tick", lambda: None)
        monkeypatch.setattr(worker_module, "run_parsing_batch", lambda: None)
        monkeypatch.setattr(worker_module, "run_ai_batch", lambda: None)
        calls = []
        monkeypatch.setattr(worker_module, "maybe_prune_app_logs", lambda: calls.append(1))

        worker_module.tick()

        assert calls == [1]
