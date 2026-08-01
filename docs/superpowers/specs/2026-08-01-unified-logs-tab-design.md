# Unified Logs Tab — Design

## Purpose

Add a "Logs" tab to the dashboard, shared via `core/` so it appears identically
across all three city instantiations (Ventura, Santa Cruz, Boston). It gives a
single, live-updating, filterable view over three previously-scattered signal
sources:

- **Pipeline** — per-source ingestion attempts (`Fetch` rows: fetch ok/error,
  HTTP status, item counts, validation issues)
- **Errors** — application-level errors, currently visible only in Docker
  logs (worker crashes, unhandled exceptions), not queryable anywhere today
- **Inference requests** — per-document AI task runs (`AiOutput` rows:
  classification, summarization, agenda-item/meeting-results extraction,
  model name, confidence, errors)

Today, error-level events (`logger.exception(...)` calls in `worker.py`) are
DB-invisible — the only place to see a crash is `docker logs`. This is the gap
this feature closes, alongside surfacing the two log-like tables that already
exist but have no dedicated view.

## Non-goals

- No cross-city aggregation — each city has its own Postgres database and its
  own dashboard process; the Logs tab shows only that city's data, same as
  every other page in the app.
- No deep historical log browsing/search — this is a live-tail-style view
  with basic cursor pagination ("Load more"), not a full log-analytics tool.
- No change to log *levels* captured beyond `ERROR` and above (no `INFO`/
  `DEBUG` capture into the DB) — those remain in Docker/stdout logs only.

## Data model

New table, in `core/app/models.py` (applies to all three cities via the
shared engine):

```python
class AppLog(Base):
    __tablename__ = "app_logs"

    id: Mapped[uuid.UUID] = uuid_pk()
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    level: Mapped[str] = mapped_column(Text, nullable=False)       # ERROR, CRITICAL
    logger_name: Mapped[str] = mapped_column(Text, nullable=False) # e.g. "app.worker"
    message: Mapped[str] = mapped_column(Text, nullable=False)
    traceback: Mapped[str | None] = mapped_column(Text)            # formatted exc_info, if present
    source_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("sources.id"), nullable=True)
```

No migration framework exists in this codebase — `scripts/init_db.py` just
calls `Base.metadata.create_all(bind=engine)`, which is safe to re-run and
will create the new `app_logs` table on its own without touching existing
tables. Adding the `AppLog` class to `models.py` is sufficient; each city's
already-running database just needs `init_db.py` re-run once to pick up the
new table.

## Logging handler ("no error left out")

`core/app/log_handler.py` defines `DbLogHandler(logging.Handler)`:

- On `emit(record)`: opens a short-lived DB session, inserts an `AppLog` row
  from `record.levelname`, `record.name`, the formatted message, the
  formatted traceback (`self.format(record)` includes `exc_info` when
  present — extract/format separately so `traceback` and `message` aren't
  duplicated), and `getattr(record, "source_id", None)`.
- **Must never raise out of `emit()`.** Wrap the DB insert in
  `try/except Exception: pass` (optionally with a `print(..., file=sys.stderr)`
  fallback) so a DB outage during error logging cannot crash the very code
  path that's already failing.
- Attached at `level=logging.ERROR` to the **root logger**, once in
  `worker.py`'s existing `logging.basicConfig(...)` setup and once at
  `main.py` startup (the API process). This is process-wide — any future
  `logger.error(...)` / `logger.exception(...)` anywhere in the app is
  captured automatically, with no per-call-site changes required.

The 3 existing `logger.exception(...)` call sites in `worker.py` (ingestion
crash, parsing crash, AI-pipeline crash) each gain
`extra={"source_id": source.id}` (or the relevant document's `source_id` for
the AI-pipeline one) so those specific errors are filterable by source.
Errors without a known source (e.g. `"worker tick failed"`) have
`source_id = None` and show under "general" when a specific source is
selected, or always show under "All sources".

## Unified API endpoint

New `core/app/routers/logs.py`, mounted at `/api/logs`, following the
existing router convention (see `core/app/routers/sources.py`).

New schema in `core/app/schemas.py`:

```python
class LogEntryOut(BaseModel):
    id: str
    type: Literal["pipeline", "error", "inference"]
    timestamp: datetime
    level: str            # normalized: "ok" | "error" | "ERROR" | "CRITICAL"
    source_id: str | None
    source_name: str | None
    summary: str           # one-line summary
    detail: str | None     # traceback / validation_message / error_message
```

`GET /api/logs` query params:

| Param | Values | Default | Meaning |
|---|---|---|---|
| `type` | `pipeline` \| `error` \| `inference` \| `all` | `all` | which underlying table(s) to query |
| `source_id` | UUID \| `all` | `all` | filters `Fetch.source_id`, `AiOutput`'s document's `source_id` (joined), `AppLog.source_id` |
| `before` | `<timestamp>,<id>` cursor | none | load entries older than this (pagination) |
| `after` | `<timestamp>,<id>` cursor | none | load entries newer than this (polling) |
| `limit` | int | 200 | max rows returned |

Implementation: query each of the three tables independently (respecting
`type`/`source_id`/cursor filters), map rows to `LogEntryOut`, merge, sort by
`(timestamp desc, id desc)`, truncate to `limit`. Mapping per type:

- **pipeline** (`Fetch`): `timestamp = fetched_at`, `level = status`,
  `summary = f"{source.name}: {status}"` (+ HTTP status / item count when
  useful), `detail = error_message or validation_message`
- **error** (`AppLog`): `timestamp = created_at`, `level = level`,
  `summary = message` (first line / truncated), `detail = traceback`
- **inference** (`AiOutput`): `timestamp = created_at`,
  `level = "error" if error_message else "ok"`,
  `summary = f"{task_type} via {model_name}"`, `detail = error_message`;
  `source_name` resolved via `Document.source_id → Source.name` (only when
  `input_ref_type == "document"`, the only ref type in current use)

## Page & UI

`core/app/dashboard.py`: new `GET /logs` route renders a template shell
(filter bar + empty table) and passes the list of `Source` rows for the
dropdown. All row data is fetched and rendered client-side via `/api/logs` —
this keeps one source of truth for row formatting (JS) instead of duplicating
it in Jinja and JS, and makes "prepend new rows on poll" straightforward.

`core/app/templates/logs.html` (extends `base.html`):

- Filter bar: **Type** select (All / Pipeline / Errors / Inference),
  **Source** select (All sources + each `Source.name`), **Auto-update**
  checkbox, checked by default
- Table: Timestamp | Type badge (reuse existing `.badge`/`.level-*` CSS
  classes from `base.html`) | Source | Summary; each row expandable via
  `<details>` to show `detail` when present
- "Load more" button at the bottom, using a `before` cursor

Behavior:

- Changing the type or source filter clears the table and re-fetches from
  scratch (cursor reset).
- While the auto-update checkbox is checked, a `setInterval` polls
  `/api/logs?after=<newest row's cursor>` every 5s and prepends new rows to
  the top; unchecking clears the interval. Not persisted across reloads —
  every page load starts with it on, per the requirement.
- Add `<a href="/logs">Logs</a>` to `base.html`'s nav — since `base.html` is
  shared core, this appears identically on all three cities' dashboards.

## Retention

`prune_app_logs(db)`: deletes `AppLog` rows where
`created_at < now() - interval '30 days'`. Called from the worker's tick
loop, throttled to run at most once per day via an in-memory
"last pruned" timestamp in the worker process (avoids a DELETE on every
60s tick). `Fetch` and `AiOutput` rows are **not** pruned — they're part of
the existing archive/audit record, not transient logs.

## Testing scope

- `DbLogHandler.emit()` writes a row for `ERROR`/`CRITICAL` records
  (including `exc_info` → `traceback`), and a DB failure inside `emit()`
  does not propagate (mock the session to raise, assert no exception escapes)
- `/api/logs`: type filter, source filter, `before`/`after` cursor
  pagination, and cross-table merge/sort order, using fixture rows across
  `Fetch`, `AiOutput`, and `AppLog`
- `prune_app_logs`: deletes only rows older than the 30-day cutoff, leaves
  newer rows and other tables untouched

## Rollout

This is a `core/` change — implementing once applies to Ventura, Santa Cruz,
and Boston simultaneously (same engine, no per-city code). Each city's
`docker-compose.yml`/deployment needs no changes; the new table is created by
the standard `init_db.py` path already used per-city.
