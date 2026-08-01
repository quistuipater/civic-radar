# Unified Logs Tab Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "Logs" tab to the dashboard (shared `core/`, so it applies to all three cities) showing pipeline activity (`Fetch` rows), application errors (a new `app_logs` table capturing every `ERROR`+ log record process-wide), and AI inference requests (`AiOutput` rows) in one timestamp-sorted, source-filterable, auto-updating table.

**Architecture:** A `logging.Handler` subclass writes every `ERROR`+ record from the root logger to a new `AppLog` table — attached once in the worker process and once in the API process, so no future `logger.error(...)`/`logger.exception(...)` call site needs to change. A new `/api/logs` endpoint merges `Fetch`, `AppLog`, and `AiOutput` rows into one normalized, cursor-paginated feed. A new `/logs` dashboard page renders that feed client-side via `fetch()`, polling every 5s (auto-update checkbox, default on) and supporting "Load more" for older entries.

**Tech Stack:** FastAPI + SQLAlchemy + Jinja2 (existing conventions), vanilla JS (no framework — matches the rest of the dashboard), pytest against a real Postgres test DB (existing `core/tests/conftest.py` fixtures).

## Global Constraints

- Spec: `docs/superpowers/specs/2026-08-01-unified-logs-tab-design.md` — every task below implements one section of it.
- No migration framework exists in this codebase. Adding a model class to `core/app/models.py` is sufficient; `scripts/init_db.py`'s `Base.metadata.create_all(bind=engine)` picks it up and is safe to re-run against an already-populated database.
- This is a `core/` change — implementing it once applies identically to Ventura, Santa Cruz, and Boston (shared engine, no per-city code).
- Follow existing conventions exactly: routers live in `core/app/routers/`, are mounted under `/api/...`, and use `ORMModel`/`BaseModel` schemas from `core/app/schemas.py`; dashboard pages live in `core/app/dashboard.py` + `core/app/templates/`; tests live in `core/tests/`, use the `client`/`db`/`db_session_factory` fixtures from `core/tests/conftest.py`, and follow the `TestXxx` class-per-behavior-group style already used throughout that directory.
- Retention: `AppLog` rows older than 30 days are pruned; `Fetch` and `AiOutput` rows are never pruned (they're part of the archive/audit record, not transient logs).

---

### Task 1: `AppLog` model, `DbLogHandler`, and log retention

**Files:**
- Modify: `core/app/models.py` (append `AppLog` class at end of file, after `CrimeIncident`)
- Create: `core/app/log_handler.py`
- Modify: `core/tests/conftest.py` (add `AppLog` to the models import, add `make_app_log` factory)
- Test: `core/tests/test_log_handler.py`

**Interfaces:**
- Produces: `app.models.AppLog` (columns: `id`, `created_at`, `level: str`, `logger_name: str`, `message: str`, `traceback: str | None`, `source_id: uuid.UUID | None`)
- Produces: `app.log_handler.DbLogHandler(session_factory)` — a `logging.Handler` subclass; `session_factory` is any zero-arg callable returning a SQLAlchemy `Session` (matches how `worker.py` already uses `SessionLocal`)
- Produces: `app.log_handler.prune_app_logs(db: Session, cutoff: datetime | None = None) -> int` — deletes and returns the count of `AppLog` rows with `created_at < cutoff` (default cutoff: 30 days ago)
- Produces: `conftest.make_app_log(db, **overrides) -> AppLog`

- [ ] **Step 1: Add the `AppLog` model**

Append to `core/app/models.py`, after the `CrimeIncident` class at the end of the file:

```python
class AppLog(Base):
    """A captured ERROR+ log record, written by DbLogHandler (see
    app/log_handler.py) from every logger in the process. Exists so
    application errors (worker crashes, unhandled exceptions) are visible
    in the dashboard's Logs tab instead of only in Docker/stdout logs.
    """

    __tablename__ = "app_logs"

    id: Mapped[uuid.UUID] = uuid_pk()
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    level: Mapped[str] = mapped_column(Text, nullable=False)
    logger_name: Mapped[str] = mapped_column(Text, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    traceback: Mapped[str | None] = mapped_column(Text)
    source_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("sources.id"), nullable=True)
```

- [ ] **Step 2: Add the `make_app_log` test factory**

In `core/tests/conftest.py`, add `AppLog` to the existing `from app.models import (...)` block (alphabetical, between `Alert` and `Document`), then add this function near the other `make_*` helpers (e.g. after `make_alert`):

```python
def make_app_log(db, **overrides) -> AppLog:
    defaults = dict(
        level="ERROR",
        logger_name="app.test",
        message="Something broke",
    )
    defaults.update(overrides)
    app_log = AppLog(**defaults)
    db.add(app_log)
    db.flush()
    return app_log
```

- [ ] **Step 3: Write the failing tests for `DbLogHandler` and `prune_app_logs`**

Create `core/tests/test_log_handler.py`:

```python
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

from .conftest import make_app_log, utcnow


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
        source_id = uuid.uuid4()
        try:
            logger.error("scoped error", extra={"source_id": source_id})
        finally:
            logger.removeHandler(handler)

        row = db.query(AppLog).one()
        assert row.source_id == source_id

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
```

- [ ] **Step 4: Run the tests to verify they fail**

Run: `pytest core/tests/test_log_handler.py -v`
Expected: FAIL/ERROR on collection — `ModuleNotFoundError: No module named 'app.log_handler'`

- [ ] **Step 5: Implement `app/log_handler.py`**

Create `core/app/log_handler.py`:

```python
"""Process-wide error capture: DbLogHandler mirrors every ERROR+ log record
into the app_logs table, so operational errors show up in the dashboard's
Logs tab instead of only in Docker/stdout logs. Attached once, to the root
logger, in worker.py's main() and main.py's startup event -- any
logger.error()/logger.exception() call anywhere in the app is captured
automatically, with no per-call-site changes required.

prune_app_logs implements the 30-day retention policy for this table (see
worker.py's maybe_prune_app_logs for the throttled call site).
"""

import logging
import sys
import traceback as traceback_module
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models import AppLog


class DbLogHandler(logging.Handler):
    def __init__(self, session_factory):
        super().__init__()
        self.session_factory = session_factory

    def emit(self, record: logging.LogRecord) -> None:
        # Must never raise: emit() is called synchronously from
        # logger.error()/.exception() call sites throughout the app, and a
        # handler exception here is NOT swallowed by the logging module --
        # it would propagate straight out of the very code path that's
        # already failing. A DB outage while logging an error must not
        # crash the caller.
        try:
            tb = None
            if record.exc_info:
                tb = "".join(traceback_module.format_exception(*record.exc_info))
            db = self.session_factory()
            try:
                db.add(
                    AppLog(
                        level=record.levelname,
                        logger_name=record.name,
                        message=record.getMessage(),
                        traceback=tb,
                        source_id=getattr(record, "source_id", None),
                    )
                )
                db.commit()
            finally:
                db.close()
        except Exception as exc:
            print(f"DbLogHandler failed to write log record: {exc}", file=sys.stderr)


def prune_app_logs(db: Session, cutoff: datetime | None = None) -> int:
    """Delete app_logs rows older than `cutoff` (default: 30 days ago).
    Returns the number of rows deleted."""
    if cutoff is None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    deleted = db.query(AppLog).filter(AppLog.created_at < cutoff).delete(synchronize_session=False)
    db.commit()
    return deleted
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `pytest core/tests/test_log_handler.py -v`
Expected: PASS (7 tests)

- [ ] **Step 7: Commit**

```bash
git add core/app/models.py core/app/log_handler.py core/tests/conftest.py core/tests/test_log_handler.py
git commit -m "Add AppLog model, DbLogHandler, and 30-day log retention"
```

---

### Task 2: Wire the handler, source tagging, and retention into `worker.py` and `main.py`

**Files:**
- Modify: `core/app/worker.py`
- Modify: `core/app/main.py`
- Test: `core/tests/test_worker.py` (add classes)
- Test: `core/tests/test_main.py` (new file)

**Interfaces:**
- Consumes: `app.log_handler.DbLogHandler(session_factory)`, `app.log_handler.prune_app_logs(db, cutoff=None) -> int` (from Task 1)
- Produces: `worker.maybe_prune_app_logs() -> None` — throttled wrapper, at most once per `worker.PRUNE_INTERVAL` (1 day)
- Produces: `main._configure_error_logging() -> None` — attaches a `DbLogHandler` to the root logger at `ERROR` level

- [ ] **Step 1: Write the failing tests**

In `core/tests/test_worker.py`, add these imports at the top (alongside the existing ones) and these test classes at the end of the file:

```python
import logging
from datetime import datetime, timedelta, timezone
```

```python
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
```

Create `core/tests/test_main.py`:

```python
"""Tests for app.main's process-wide error-logging setup. _configure_error_logging
is registered as a FastAPI startup event handler, which does NOT fire for
the plain `TestClient(app)` instance used throughout this test suite (only
`with TestClient(app) as client:` triggers lifespan events) -- so it's
tested directly here as a plain function instead of via the `client` fixture.
"""

import logging

import app.main as main_module
from app.log_handler import DbLogHandler


def test_configure_error_logging_attaches_a_db_log_handler():
    root = logging.getLogger()
    original_handlers = list(root.handlers)
    try:
        main_module._configure_error_logging()

        added = [h for h in root.handlers if isinstance(h, DbLogHandler)]
        assert len(added) == 1
        assert added[0].level == logging.ERROR
    finally:
        root.handlers = original_handlers
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest core/tests/test_worker.py core/tests/test_main.py -v`
Expected: FAIL — `test_worker.py`'s new tests fail because the crash-site `extra={"source_id": ...}` isn't there yet (assertion error, `record.source_id` raises `AttributeError`) and `worker_module.maybe_prune_app_logs`/`worker_module._last_prune_at`/`prune_app_logs` don't exist yet (`AttributeError` from `monkeypatch.setattr`); `test_main.py` fails with `AttributeError: module 'app.main' has no attribute '_configure_error_logging'`

- [ ] **Step 3: Implement the worker.py changes**

In `core/app/worker.py`, update the imports (add to the existing import block):

```python
from app.log_handler import DbLogHandler, prune_app_logs
```

Change the three `except Exception:` blocks to tag `source_id`:

In `run_ingestion_tick`:
```python
            except Exception:
                db.rollback()
                logger.exception("ingestion crashed for source %s", source.name, extra={"source_id": source.id})
```

In `run_parsing_batch`:
```python
            except Exception:
                db.rollback()
                logger.exception("parsing crashed for document %s", document.id, extra={"source_id": document.source_id})
```

In `run_ai_batch`:
```python
            except Exception:
                db.rollback()
                logger.exception("AI pipeline crashed for document %s", document.id, extra={"source_id": document.source_id})
```

Add the retention throttle (after `BATCH_SIZE = 25`):

```python
_last_prune_at: datetime | None = None
PRUNE_INTERVAL = timedelta(days=1)


def maybe_prune_app_logs() -> None:
    global _last_prune_at
    now = datetime.now(timezone.utc)
    if _last_prune_at is not None and now - _last_prune_at < PRUNE_INTERVAL:
        return
    db = SessionLocal()
    try:
        prune_app_logs(db)
    finally:
        db.close()
    _last_prune_at = now
```

Update `tick()` to call it:

```python
def tick() -> None:
    run_ingestion_tick()
    run_parsing_batch()
    run_ai_batch()
    maybe_prune_app_logs()
```

Update `main()` to attach the handler before the loop starts:

```python
def main() -> None:
    handler = DbLogHandler(SessionLocal)
    handler.setLevel(logging.ERROR)
    logging.getLogger().addHandler(handler)
    logger.info("%s worker starting (tick every %ss)", settings.project_name, settings.worker_tick_seconds)
    while True:
        try:
            tick()
        except Exception:
            logger.exception("worker tick failed")
        time.sleep(settings.worker_tick_seconds)
```

- [ ] **Step 4: Implement the main.py changes**

In `core/app/main.py`, add imports and the startup handler. The `logs` router is registered separately in Task 3 (it doesn't exist yet) — this step only adds the `DbLogHandler` startup wiring:

```python
import logging

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app import dashboard
from app.config import settings
from app.db import SessionLocal
from app.log_handler import DbLogHandler
from app.routers import (
    alerts,
    crime_incidents,
    digest,
    documents,
    issues,
    manual_submissions,
    meetings,
    review,
    search,
    sources,
)

app = FastAPI(title=settings.project_name, version="0.1.0")

app.include_router(sources.router)
app.include_router(documents.router)
app.include_router(meetings.router)
app.include_router(issues.router)
app.include_router(alerts.router)
app.include_router(review.router)
app.include_router(search.router)
app.include_router(manual_submissions.router)
app.include_router(digest.router)
app.include_router(crime_incidents.router)
app.include_router(dashboard.router)

app.mount("/archive", StaticFiles(directory=settings.archive_root), name="archive")


def _configure_error_logging() -> None:
    handler = DbLogHandler(SessionLocal)
    handler.setLevel(logging.ERROR)
    logging.getLogger().addHandler(handler)


app.add_event_handler("startup", _configure_error_logging)


@app.get("/healthz")
def healthz():
    return {"status": "ok"}
```

This is the same file layout as today plus the `logging`/`SessionLocal`/`DbLogHandler` imports and the `_configure_error_logging`/`add_event_handler` block — no other route registrations change in this step.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest core/tests/test_worker.py core/tests/test_main.py -v`
Expected: PASS (all new tests, plus the existing worker tests still passing)

- [ ] **Step 6: Commit**

```bash
git add core/app/worker.py core/app/main.py core/tests/test_worker.py core/tests/test_main.py
git commit -m "Wire DbLogHandler and log retention into worker and API processes"
```

---

### Task 3: `LogEntryOut` schema and the unified `/api/logs` endpoint

**Files:**
- Modify: `core/app/schemas.py` (append `LogEntryOut`)
- Create: `core/app/routers/logs.py`
- Modify: `core/app/main.py` (register the router — see note at end of Task 2)
- Test: `core/tests/test_router_logs.py`

**Interfaces:**
- Consumes: `app.models.Fetch`, `app.models.AppLog`, `app.models.AiOutput`, `app.models.Document`, `app.models.Source` (existing + Task 1)
- Produces: `app.schemas.LogEntryOut` (fields: `id: str`, `type: Literal["pipeline", "error", "inference"]`, `timestamp: datetime`, `level: str`, `source_id: str | None`, `source_name: str | None`, `summary: str`, `detail: str | None`)
- Produces: `GET /api/logs` — query params `type` (`pipeline`|`error`|`inference`|`all`, default `all`), `source_id` (UUID string or `all`, default `all`), `after`/`before` (ISO 8601 timestamp strings, optional), `limit` (default 200, max 1000) → `list[LogEntryOut]`, newest first

- [ ] **Step 1: Add the `LogEntryOut` schema**

In `core/app/schemas.py`, change the top import line:

```python
from typing import Literal
```

(add alongside the existing `import uuid` / `from datetime import date, datetime` / `from pydantic import BaseModel, ConfigDict` block)

Append at the end of the file:

```python
# --- Logs ---


class LogEntryOut(BaseModel):
    id: str
    type: Literal["pipeline", "error", "inference"]
    timestamp: datetime
    level: str
    source_id: str | None
    source_name: str | None
    summary: str
    detail: str | None
```

- [ ] **Step 2: Write the failing tests**

Create `core/tests/test_router_logs.py`:

```python
"""Tests for the unified /api/logs endpoint: merges Fetch (pipeline),
AppLog (error), and AiOutput (inference) rows into one timestamp-sorted
feed, with type/source filtering and after/before cursor pagination.
"""

from datetime import timedelta

from app.models import Fetch

from .conftest import make_ai_output, make_app_log, make_document, make_source, utcnow


class TestListLogsByType:
    def test_pipeline_entries_include_source_name_and_status(self, client, db):
        source = make_source(db, name="Agenda Source")
        db.add(Fetch(source_id=source.id, status="ok", http_status=200, items_found=5))
        db.commit()

        resp = client.get("/api/logs?type=pipeline")

        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 1
        assert body[0]["type"] == "pipeline"
        assert body[0]["source_name"] == "Agenda Source"
        assert body[0]["level"] == "ok"
        assert "Agenda Source: ok" in body[0]["summary"]
        assert "5 items" in body[0]["summary"]

    def test_error_entries_carry_message_and_traceback(self, client, db):
        make_app_log(db, message="worker tick failed", traceback="Traceback...\nRuntimeError: boom")
        db.commit()

        resp = client.get("/api/logs?type=error")

        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 1
        assert body[0]["type"] == "error"
        assert body[0]["summary"] == "worker tick failed"
        assert body[0]["detail"] == "Traceback...\nRuntimeError: boom"

    def test_inference_entries_include_task_and_model_in_summary(self, client, db):
        source = make_source(db, name="Inference Source")
        document = make_document(db, source=source)
        make_ai_output(db, document.id, task_type="classification", model_name="qwen3:8b")
        db.commit()

        resp = client.get("/api/logs?type=inference")

        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 1
        assert body[0]["type"] == "inference"
        assert body[0]["level"] == "ok"
        assert body[0]["summary"] == "classification via qwen3:8b"
        assert body[0]["source_name"] == "Inference Source"

    def test_inference_entry_with_error_message_has_error_level(self, client, db):
        document = make_document(db)
        make_ai_output(db, document.id, error_message="ollama unreachable")
        db.commit()

        resp = client.get("/api/logs?type=inference")

        body = resp.json()
        assert body[0]["level"] == "error"
        assert body[0]["detail"] == "ollama unreachable"

    def test_all_type_merges_and_sorts_newest_first(self, client, db):
        source = make_source(db)
        now = utcnow()
        db.add(Fetch(source_id=source.id, status="ok", fetched_at=now - timedelta(minutes=2)))
        make_app_log(db, message="most recent", created_at=now)
        document = make_document(db, source=source)
        make_ai_output(db, document.id, created_at=now - timedelta(minutes=1))
        db.commit()

        resp = client.get("/api/logs?type=all")

        body = resp.json()
        assert [e["type"] for e in body] == ["error", "inference", "pipeline"]


class TestListLogsBySource:
    def test_strict_source_filter_for_pipeline(self, client, db):
        matching = make_source(db, name="Matching")
        other = make_source(db, name="Other")
        db.add(Fetch(source_id=matching.id, status="ok"))
        db.add(Fetch(source_id=other.id, status="ok"))
        db.commit()

        resp = client.get(f"/api/logs?type=pipeline&source_id={matching.id}")

        body = resp.json()
        assert len(body) == 1
        assert body[0]["source_name"] == "Matching"

    def test_error_filter_includes_general_errors_with_no_source(self, client, db):
        matching = make_source(db, name="Matching")
        other = make_source(db, name="Other")
        make_app_log(db, message="scoped to matching", source_id=matching.id)
        make_app_log(db, message="scoped to other", source_id=other.id)
        make_app_log(db, message="general error", source_id=None)
        db.commit()

        resp = client.get(f"/api/logs?type=error&source_id={matching.id}")

        summaries = {e["summary"] for e in resp.json()}
        assert summaries == {"scoped to matching", "general error"}

    def test_all_sources_returns_everything(self, client, db):
        make_app_log(db, message="one", source_id=make_source(db).id)
        db.commit()

        resp = client.get("/api/logs?type=error&source_id=all")

        assert len(resp.json()) == 1


class TestListLogsPagination:
    def test_after_cursor_returns_only_newer_entries(self, client, db):
        now = utcnow()
        make_app_log(db, message="old", created_at=now - timedelta(minutes=10))
        make_app_log(db, message="new", created_at=now)
        db.commit()

        resp = client.get(f"/api/logs?type=error&after={(now - timedelta(minutes=5)).isoformat()}")

        summaries = [e["summary"] for e in resp.json()]
        assert summaries == ["new"]

    def test_before_cursor_returns_only_older_entries(self, client, db):
        now = utcnow()
        make_app_log(db, message="old", created_at=now - timedelta(minutes=10))
        make_app_log(db, message="new", created_at=now)
        db.commit()

        resp = client.get(f"/api/logs?type=error&before={(now - timedelta(minutes=5)).isoformat()}")

        summaries = [e["summary"] for e in resp.json()]
        assert summaries == ["old"]

    def test_limit_is_respected(self, client, db):
        for i in range(5):
            make_app_log(db, message=f"entry-{i}")
        db.commit()

        resp = client.get("/api/logs?type=error&limit=2")

        assert len(resp.json()) == 2
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `pytest core/tests/test_router_logs.py -v`
Expected: FAIL with 404s (`/api/logs` doesn't exist yet) — also update `core/app/main.py` now so app startup doesn't error on import (`ImportError` for `logs` if left in from Task 2's note): if you added the `logs` import/registration during Task 2, it will currently fail to import since `core/app/routers/logs.py` doesn't exist yet. That's expected at this point — Step 4 creates it.

- [ ] **Step 4: Implement `app/routers/logs.py`**

Create `core/app/routers/logs.py`:

```python
"""Unified log feed: merges three existing signal sources into one
timestamp-sorted, filterable view --

- pipeline: Fetch rows (per-source ingestion attempts)
- error: AppLog rows (every ERROR+ log record process-wide, see log_handler.py)
- inference: AiOutput rows (per-document AI task runs)

Each sub-query independently applies the type/source/cursor filters and its
own `limit`, and results are merged and re-sorted before the final
truncation to `limit` -- this is deliberately more generous than a single
combined query would be, so a low-volume type (e.g. errors, hopefully) never
gets crowded out of an "all types" page by a high-volume one.
"""

import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import AiOutput, AppLog, Document, Fetch, Source
from app.schemas import LogEntryOut

router = APIRouter(prefix="/api/logs", tags=["logs"])


def _parse_source_id(raw: str | None) -> uuid.UUID | None:
    return None if raw in (None, "all") else uuid.UUID(raw)


def _pipeline_entries(
    db: Session,
    source_id: uuid.UUID | None,
    after: datetime | None,
    before: datetime | None,
    limit: int,
) -> list[LogEntryOut]:
    q = db.query(Fetch, Source.name).join(Source, Fetch.source_id == Source.id)
    if source_id is not None:
        q = q.filter(Fetch.source_id == source_id)
    if after is not None:
        q = q.filter(Fetch.fetched_at > after)
    if before is not None:
        q = q.filter(Fetch.fetched_at < before)
    q = q.order_by(Fetch.fetched_at.desc()).limit(limit)

    entries = []
    for fetch, source_name in q.all():
        summary = f"{source_name}: {fetch.status}"
        if fetch.http_status is not None:
            summary += f" (HTTP {fetch.http_status})"
        if fetch.items_found is not None:
            summary += f", {fetch.items_found} items"
        entries.append(
            LogEntryOut(
                id=str(fetch.id),
                type="pipeline",
                timestamp=fetch.fetched_at,
                level=fetch.status,
                source_id=str(fetch.source_id),
                source_name=source_name,
                summary=summary,
                detail=fetch.error_message or fetch.validation_message,
            )
        )
    return entries


def _error_entries(
    db: Session,
    source_id: uuid.UUID | None,
    after: datetime | None,
    before: datetime | None,
    limit: int,
) -> list[LogEntryOut]:
    q = db.query(AppLog, Source.name).outerjoin(Source, AppLog.source_id == Source.id)
    if source_id is not None:
        # Unlike pipeline/inference, error entries include unscoped
        # ("general") errors alongside ones tagged with this source --
        # see the design spec's source-picker section.
        q = q.filter(or_(AppLog.source_id == source_id, AppLog.source_id.is_(None)))
    if after is not None:
        q = q.filter(AppLog.created_at > after)
    if before is not None:
        q = q.filter(AppLog.created_at < before)
    q = q.order_by(AppLog.created_at.desc()).limit(limit)

    entries = []
    for app_log, source_name in q.all():
        entries.append(
            LogEntryOut(
                id=str(app_log.id),
                type="error",
                timestamp=app_log.created_at,
                level=app_log.level,
                source_id=str(app_log.source_id) if app_log.source_id else None,
                source_name=source_name,
                summary=app_log.message,
                detail=app_log.traceback,
            )
        )
    return entries


def _inference_entries(
    db: Session,
    source_id: uuid.UUID | None,
    after: datetime | None,
    before: datetime | None,
    limit: int,
) -> list[LogEntryOut]:
    q = (
        db.query(AiOutput, Source.id, Source.name)
        .outerjoin(
            Document,
            and_(AiOutput.input_ref_type == "document", AiOutput.input_ref_id == Document.id),
        )
        .outerjoin(Source, Document.source_id == Source.id)
    )
    if source_id is not None:
        q = q.filter(Source.id == source_id)
    if after is not None:
        q = q.filter(AiOutput.created_at > after)
    if before is not None:
        q = q.filter(AiOutput.created_at < before)
    q = q.order_by(AiOutput.created_at.desc()).limit(limit)

    entries = []
    for ai_output, src_id, src_name in q.all():
        entries.append(
            LogEntryOut(
                id=str(ai_output.id),
                type="inference",
                timestamp=ai_output.created_at,
                level="error" if ai_output.error_message else "ok",
                source_id=str(src_id) if src_id else None,
                source_name=src_name,
                summary=f"{ai_output.task_type} via {ai_output.model_name}",
                detail=ai_output.error_message,
            )
        )
    return entries


@router.get("", response_model=list[LogEntryOut])
def list_logs(
    type_: Literal["pipeline", "error", "inference", "all"] = Query("all", alias="type"),
    source_id: str | None = Query(default=None),
    after: str | None = Query(default=None),
    before: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
    db: Session = Depends(get_db),
) -> list[LogEntryOut]:
    parsed_source_id = _parse_source_id(source_id)
    parsed_after = datetime.fromisoformat(after) if after else None
    parsed_before = datetime.fromisoformat(before) if before else None

    entries: list[LogEntryOut] = []
    if type_ in ("pipeline", "all"):
        entries += _pipeline_entries(db, parsed_source_id, parsed_after, parsed_before, limit)
    if type_ in ("error", "all"):
        entries += _error_entries(db, parsed_source_id, parsed_after, parsed_before, limit)
    if type_ in ("inference", "all"):
        entries += _inference_entries(db, parsed_source_id, parsed_after, parsed_before, limit)

    entries.sort(key=lambda e: e.timestamp, reverse=True)
    return entries[:limit]
```

Now register the router in `core/app/main.py` — this is the edit deferred from Task 2. Add `logs` to the `from app.routers import (...)` block (alphabetical, between `issues` and `manual_submissions`) and add `app.include_router(logs.router)` (alongside the other `include_router` calls, before `app.include_router(dashboard.router)` since `dashboard.router` should stay last — it owns the `/` catch-all-ish page routes):

```python
from app.routers import (
    alerts,
    crime_incidents,
    digest,
    documents,
    issues,
    logs,
    manual_submissions,
    meetings,
    review,
    search,
    sources,
)
```

```python
app.include_router(sources.router)
app.include_router(documents.router)
app.include_router(meetings.router)
app.include_router(issues.router)
app.include_router(alerts.router)
app.include_router(review.router)
app.include_router(search.router)
app.include_router(manual_submissions.router)
app.include_router(digest.router)
app.include_router(crime_incidents.router)
app.include_router(logs.router)
app.include_router(dashboard.router)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest core/tests/test_router_logs.py -v`
Expected: PASS (11 tests)

Also run the full suite to make sure the `main.py` edits didn't break anything else:

Run: `pytest core/tests -v`
Expected: PASS (all tests, including the ones from Tasks 1 and 2)

- [ ] **Step 6: Commit**

```bash
git add core/app/schemas.py core/app/routers/logs.py core/app/main.py core/tests/test_router_logs.py
git commit -m "Add unified /api/logs endpoint merging pipeline, error, and inference logs"
```

---

### Task 4: `/logs` dashboard page, template, and nav link

**Files:**
- Modify: `core/app/dashboard.py` (add `logs_page` route)
- Create: `core/app/templates/logs.html`
- Modify: `core/app/templates/base.html` (add nav link)
- Modify: `core/tests/test_api_smoke.py` (add smoke tests)

**Interfaces:**
- Consumes: `GET /api/logs` (from Task 3), `app.models.Source` (existing)
- Produces: `GET /logs` — renders the page shell; all row data comes from client-side `fetch("/api/logs")`

- [ ] **Step 1: Write the failing smoke tests**

In `core/tests/test_api_smoke.py`, add to `TestDashboardPages` (after `test_digest_markdown_export_renders`):

```python
    def test_logs_page_renders_with_empty_database(self, client):
        resp = client.get("/logs")
        assert resp.status_code == 200

    def test_logs_page_renders_with_sources(self, client, db):
        make_source(db, name="A Logs Source")
        db.commit()
        resp = client.get("/logs")
        assert resp.status_code == 200
        assert "A Logs Source" in resp.text
```

Add to `TestHealthAndApi` (after `test_crime_incidents_api_empty`):

```python
    def test_logs_api_empty(self, client):
        resp = client.get("/api/logs")
        assert resp.status_code == 200
        assert resp.json() == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest core/tests/test_api_smoke.py -v`
Expected: FAIL — `test_logs_page_renders_with_empty_database` and `test_logs_page_renders_with_sources` get 404 (`/logs` doesn't exist); `test_logs_api_empty` should already pass since Task 3 built `/api/logs` (confirms Task 3 is done before starting this one)

- [ ] **Step 3: Add the `logs_page` route**

In `core/app/dashboard.py`, add this route immediately after `sources_page` (which ends with the `return templates.TemplateResponse(...)` for `"sources.html"`), before `review_queue_page`:

```python
@router.get("/logs")
def logs_page(request: Request, db: Session = Depends(get_db)):
    sources = db.query(Source).order_by(Source.name).all()
    return templates.TemplateResponse("logs.html", {"request": request, "sources": sources})
```

- [ ] **Step 4: Add the nav link**

In `core/app/templates/base.html`, change:

```html
    <a href="/sources">Sources</a>
```

to:

```html
    <a href="/sources">Sources</a>
    <a href="/logs">Logs</a>
```

- [ ] **Step 5: Create the `logs.html` template**

Create `core/app/templates/logs.html`:

```html
{% extends "base.html" %}
{% block title %}Logs — {{ project_name }}{% endblock %}
{% block content %}
<h1>Logs</h1>
<div class="panel">
  <label style="display:inline-block;margin-right:1.5rem;">Type
    <select id="log-type">
      <option value="all">All</option>
      <option value="pipeline">Pipeline</option>
      <option value="error">Errors</option>
      <option value="inference">Inference</option>
    </select>
  </label>
  <label style="display:inline-block;margin-right:1.5rem;">Source
    <select id="log-source">
      <option value="all">All sources</option>
      {% for s in sources %}
      <option value="{{ s.id }}">{{ s.name }}</option>
      {% endfor %}
    </select>
  </label>
  <label style="display:inline-block;">
    <input type="checkbox" id="log-autoupdate" checked> Auto-update
  </label>
</div>
<table>
  <thead>
    <tr><th>Time</th><th>Type</th><th>Source</th><th>Summary</th></tr>
  </thead>
  <tbody id="log-rows"></tbody>
</table>
<p class="empty" id="log-empty" style="display:none;">No log entries match this filter.</p>
<p><button type="button" class="secondary" id="log-load-more">Load more</button></p>

<script>
(function () {
  var rowsEl = document.getElementById('log-rows');
  var typeSel = document.getElementById('log-type');
  var sourceSel = document.getElementById('log-source');
  var autoCheckbox = document.getElementById('log-autoupdate');
  var loadMoreBtn = document.getElementById('log-load-more');
  var emptyEl = document.getElementById('log-empty');

  var seenIds = new Set();
  var newestTimestamp = null;
  var oldestTimestamp = null;
  var pollTimer = null;

  var LEVEL_CLASS = { error: 'level-4', critical: 'level-4', pending: 'level-2', ok: 'level-1' };

  function levelBadgeClass(level) {
    return LEVEL_CLASS[(level || '').toLowerCase()] || 'level-2';
  }

  function typeLabel(type) {
    return type.charAt(0).toUpperCase() + type.slice(1);
  }

  function renderRow(entry, prepend) {
    if (seenIds.has(entry.id)) return;
    seenIds.add(entry.id);

    var tr = document.createElement('tr');

    var tdTime = document.createElement('td');
    tdTime.className = 'muted';
    tdTime.textContent = new Date(entry.timestamp).toLocaleString();
    tr.appendChild(tdTime);

    var tdType = document.createElement('td');
    var badge = document.createElement('span');
    badge.className = 'badge ' + levelBadgeClass(entry.level);
    badge.textContent = typeLabel(entry.type) + ': ' + entry.level;
    tdType.appendChild(badge);
    tr.appendChild(tdType);

    var tdSource = document.createElement('td');
    tdSource.className = 'muted';
    tdSource.textContent = entry.source_name || 'general';
    tr.appendChild(tdSource);

    var tdSummary = document.createElement('td');
    if (entry.detail) {
      var details = document.createElement('details');
      var summaryEl = document.createElement('summary');
      summaryEl.textContent = entry.summary;
      details.appendChild(summaryEl);
      var pre = document.createElement('pre');
      pre.style.whiteSpace = 'pre-wrap';
      pre.style.margin = '0.4rem 0 0';
      pre.textContent = entry.detail;
      details.appendChild(pre);
      tdSummary.appendChild(details);
    } else {
      tdSummary.textContent = entry.summary;
    }
    tr.appendChild(tdSummary);

    if (prepend) {
      rowsEl.insertBefore(tr, rowsEl.firstChild);
    } else {
      rowsEl.appendChild(tr);
    }
  }

  function buildUrl(extraParams) {
    var params = { type: typeSel.value, source_id: sourceSel.value };
    for (var key in extraParams) {
      params[key] = extraParams[key];
    }
    var query = Object.keys(params)
      .filter(function (k) { return params[k] !== null && params[k] !== undefined; })
      .map(function (k) { return encodeURIComponent(k) + '=' + encodeURIComponent(params[k]); })
      .join('&');
    return '/api/logs?' + query;
  }

  function updateCursorsFromEntries(entries) {
    entries.forEach(function (entry) {
      if (newestTimestamp === null || entry.timestamp > newestTimestamp) {
        newestTimestamp = entry.timestamp;
      }
      if (oldestTimestamp === null || entry.timestamp < oldestTimestamp) {
        oldestTimestamp = entry.timestamp;
      }
    });
  }

  function loadInitial() {
    rowsEl.innerHTML = '';
    seenIds.clear();
    newestTimestamp = null;
    oldestTimestamp = null;
    fetch(buildUrl({}))
      .then(function (r) { return r.json(); })
      .then(function (entries) {
        entries.forEach(function (entry) { renderRow(entry, false); });
        updateCursorsFromEntries(entries);
        emptyEl.style.display = entries.length === 0 ? 'block' : 'none';
      });
  }

  function poll() {
    if (newestTimestamp === null) { loadInitial(); return; }
    fetch(buildUrl({ after: newestTimestamp }))
      .then(function (r) { return r.json(); })
      .then(function (entries) {
        // server returns newest-first; reverse so the final prepend order
        // in the DOM stays newest-first at the top
        entries.slice().reverse().forEach(function (entry) { renderRow(entry, true); });
        updateCursorsFromEntries(entries);
      });
  }

  function loadMore() {
    if (oldestTimestamp === null) return;
    fetch(buildUrl({ before: oldestTimestamp }))
      .then(function (r) { return r.json(); })
      .then(function (entries) {
        entries.forEach(function (entry) { renderRow(entry, false); });
        updateCursorsFromEntries(entries);
      });
  }

  function startAutoUpdate() {
    stopAutoUpdate();
    pollTimer = setInterval(poll, 5000);
  }

  function stopAutoUpdate() {
    if (pollTimer !== null) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
  }

  typeSel.addEventListener('change', loadInitial);
  sourceSel.addEventListener('change', loadInitial);
  loadMoreBtn.addEventListener('click', loadMore);
  autoCheckbox.addEventListener('change', function () {
    if (autoCheckbox.checked) { startAutoUpdate(); } else { stopAutoUpdate(); }
  });

  loadInitial();
  if (autoCheckbox.checked) { startAutoUpdate(); }
})();
</script>
{% endblock %}
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `pytest core/tests/test_api_smoke.py -v`
Expected: PASS (all tests in the file)

Run the full suite one more time:

Run: `pytest core/tests -v`
Expected: PASS (everything)

- [ ] **Step 7: Commit**

```bash
git add core/app/dashboard.py core/app/templates/logs.html core/app/templates/base.html core/tests/test_api_smoke.py
git commit -m "Add /logs dashboard page with type/source filters and auto-update"
```

---

## Manual verification (not covered by automated tests)

`worker.main()` runs an infinite loop and isn't unit-tested directly — its two changes (attaching `DbLogHandler`, calling `tick()` which now includes `maybe_prune_app_logs()`) are covered indirectly through the tested pieces they call. After deploying, confirm end-to-end behavior once per city:

1. `docker compose run --rm api python scripts/init_db.py` — creates the `app_logs` table on the already-running database (safe, additive-only).
2. `docker compose up -d api worker` (or restart if already running).
3. Open `http://localhost:<city-port>/logs` — should render with the type/source filters and an empty or populated table.
4. Trigger a real error (e.g., temporarily point `ollama_base_url` at an unreachable host, or just wait for a natural ingestion hiccup) and confirm it appears under "Errors" within one worker tick, tagged with the right source when applicable.
5. Leave the page open for >5s with auto-update checked and confirm new rows appear without a manual refresh; uncheck it and confirm polling stops (e.g., via the browser's network tab).

## Rollout

This is a `core/` change — merging it applies to Ventura, Santa Cruz, and Boston simultaneously. Each city needs step 1 above (`init_db.py` re-run) once against its already-running database; no `docker-compose.yml` changes are needed anywhere.
