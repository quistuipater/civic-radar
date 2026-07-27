# Santa Cruz Civic Radar

*This is the Santa Cruz instantiation of the Civic Radar platform — see the
repo root's [`OVERVIEW.md`](../../OVERVIEW.md) for the shared engine,
architecture, and design principles this deployment builds on. This document
covers only what's actually specific to Santa Cruz.*

Phase 0 prototype of the local-first civic intelligence system described in
`../../prd.md`. It archives government sources (agendas, staff reports, notices),
extracts and classifies them, tracks them as "issues" over time, and
generates reviewable alerts and Markdown briefs — all runnable on a single
Docker Compose stack.

**Core principle: archive first, interpret second, publish third.** Nothing is
summarized or classified without the raw source material being hashed and
saved to `/archive` first.

**This instantiation was originally a fork of Ventura Civic Radar** (now
`../ventura/` in this same monorepo), **brought to operational parity
2026-07-10** — 8 real sources seeded and
ingesting live Santa Cruz city/county government material end-to-end
(fetch → archive → parse → AI classification/summarization/agenda-item
extraction/meeting-results extraction), verified against real Ollama calls
on `madhatter.local`. Two of those sources needed genuinely new connector
code (not just configuration) since Santa Cruz's real platforms differ from
Ventura's — see "What's implemented" below for exactly what's real and what
required new engineering, and "Known gaps" for what's still open (crime
data, county meeting audio).

## What's implemented

- **Source registry**: `backend/scripts/seed_sources.py` seeds **8 real,
  live-verified sources** (2026-07-10):
  - City of Santa Cruz council/commission agendas (OnBase Agenda Online)
  - Santa Cruz County Board of Supervisors (PrimeGov)
  - Santa Cruz County Planning Commission (legacy ASP search tool)
  - Campaign finance + Statement of Economic Interests, county (NetFile,
    `SCCO`) and city (NetFile, `CRUZ`) — 4 feeds total
  - Santa Cruz County Elections Division
  
  A real end-to-end ingestion run against all 8 produced 227 documents
  (63 county PrimeGov agendas/packets + NetFile/Elections filings, 149
  City of Santa Cruz OnBase documents across a dozen+ boards/committees, 15
  County Planning Commission agendas/minutes) and 30+ real `Meeting` rows,
  correctly linked to their agenda/packet/minutes documents.
- **Ingestion connectors**:
  - `app/ingestion/connectors/primegov.py` — generic, unmodified from
    Ventura. Confirmed live against `santacruzcountyca.primegov.com` for
    the Board of Supervisors.
  - `app/ingestion/connectors/netfile_rss.py` — generic, unmodified from
    Ventura. Confirmed live against both `SCCO` (county) and `CRUZ` (city)
    agency codes.
  - `app/ingestion/connectors/generic.py` — generic, unmodified from
    Ventura. Confirmed live against the county Elections page (no bot wall
    here, unlike Ventura's).
  - `app/ingestion/onbase_agenda.py` — **new, Santa-Cruz-specific.** City of
    Santa Cruz's agenda platform is Hyland OnBase, not CivicPlus. Document
    downloads need a 2-step session-stateful POST-then-GET flow (not a
    plain link), so this bypasses the generic connector dispatch — see the
    module docstring for the full flow.
  - `app/ingestion/scc_planning_search.py` — **new, Santa-Cruz-specific.**
    The county Planning Commission runs on a separate, much older platform
    than the Board of Supervisors (a Microsoft Indexing Service-era classic
    ASP full-text search tool, not PrimeGov) — also session-stateful, also
    bypasses the generic dispatch.
  - `app/ingestion/arcgis_feature_service.py` + `app/ingestion/crime_data.py`
    — generic, unmodified from Ventura, but `AGENCY_CONFIG` is still empty:
    no incident-level crime data feed was found for either the City of
    Santa Cruz PD or the County Sheriff (checked both agencies' ArcGIS Hubs
    directly — only jurisdiction-boundary layers exist, no incidents).
  - `app/ingestion/meeting_audio.py` + `whisperx_service/` — generic,
    unmodified from Ventura, but **not usable as-is here**: the county's
    Granicus podcast RSS feed (what this connector reads) returns zero
    items despite 200+ real recordings existing, and both the county's and
    city's actual video streams are CloudFront-gated (confirmed via a
    direct request with a matching Referer header, still 403) — see
    "Known gaps" below.
  - Every fetch archives raw material first regardless of what else it finds
    (archive-first).
- **Parsing**: PDF (`pdfplumber`) and HTML text extraction, page-level
  chunking, regex-based structured field extraction (ordinance/resolution/
  project numbers, APNs, comment deadlines, public hearing dates). OCR
  fallback (`pytesseract`/`pdf2image`) for scanned/image-only pages, with an
  OCR-attempts cap and a wall-clock parse budget so pathological inputs
  can't take down the worker.
- **AI layer**: local Ollama client for classification, summarization,
  embeddings, agenda-item extraction, and meeting-results extraction (what
  *actually happened* at a meeting, distinct from what was proposed), with a
  deterministic heuristic fallback for classification when Ollama is
  unreachable. Prompts are versioned in the `prompts` table
  (`backend/app/ai/prompts.py`) and already reference "Santa Cruz Civic
  Radar" rather than Ventura's name. **Model note carried over from
  Ventura**: `gpt-oss:20b` produced garbled output when tested on
  `madhatter.local` (likely an MXFP4/kernel issue) —
  `OLLAMA_TRIAGE_MODEL`/`OLLAMA_ANALYSIS_MODEL` default to `llama3.1:8b`;
  re-verify before changing either, especially if pointing at a different
  Ollama instance than Ventura's.
- **Semantic search**: `document_chunks.embedding` (pgvector), `/api/search`
  returns cosine-similarity matches alongside keyword results.
- **Issue tracking**: manual issue creation, high-confidence auto-linking by
  exact project/ordinance/resolution number, fuzzy semantic suggestions
  (human-confirmed, deliberately not auto-linked — see
  `app/issue_matching.py` for why), and a Markdown issue brief exporter.
- **Daily digest**: `/digest` in the dashboard or `GET /api/digest/daily.md`
  — top changes, upcoming hearings/votes, new notices, items needing
  review, approaching deadlines, low-confidence/unverified claims.
- **Alerts**: levels 1-4 per `prd.md` section 12, deduplicated per
  document+level.
- **Dashboard**: server-rendered (Jinja2, no build step) — home, review
  queue, sources, issues, meeting/document/transcript detail, manual
  submission form. Action buttons (Run classification, Attach, Approve/Reject,
  Create issue, Submit) show "Working…" and disable on click via a small
  global script in `base.html`. Local archive paths on document/transcript
  detail pages are clickable — `/archive` is mounted as a static file route
  (`app/main.py`) serving directly from `settings.archive_root`, so the
  archived file opens in a new tab.
- **REST API**: FastAPI, routes per `prd.md` section 17.
- **Test suite**: pytest — see "Running tests" below for current counts.
  Fixture defaults (`../../core/tests/conftest.py`) use "City of Santa Cruz" rather
  than Ventura's jurisdiction name, but most individual tests exercise
  generic logic and don't depend on the actual city name.

## Known gaps (by design, not oversight)

- **Local police/sheriff open crime data — not found.** Checked both the
  City of Santa Cruz's ArcGIS Hub (`data1-cruzgis.opendata.arcgis.com`, 59
  datasets) and the County's (`opendata-sccgis.opendata.arcgis.com`, 176
  datasets) — both have only jurisdiction-*boundary* layers ("Police Beats",
  "Sheriff Beats"), no incident-level dataset. The city's own crime-stats
  page (`www.santacruzca.gov/...`) is behind a site-wide Akamai bot wall
  (confirmed 403 on the bare root page even with a browser UA) — not
  pursued, consistent with this project's standing policy against bypassing
  bot challenges. `AGENCY_CONFIG` in `crime_data.py` stays empty.
- **Meeting audio/video — not wired in.** County has a real Granicus
  instance (`santacruzcountyca.granicus.com`) with 200+ real video
  recordings going back to 2019 (confirmed via `ViewPublisher.php?view_id=2`),
  but its `Podcast.php` RSS feed (what `meeting_audio.py` reads) returns
  **zero items** across every `view_id` tried — podcast syndication isn't
  populated on this instance, unlike Ventura's. The county's actual video
  stream is a Wowza-backed HLS playlist behind CloudFront
  (`archive-stream.granicus.com/OnDemand/...`) that returns 403 even with a
  matching `Referer` header — genuinely access-controlled, not just a
  UA-string filter, so not pursued further (same boundary as the crime-data
  bot wall above). City's OnBase platform has its own media player serving
  a similarly tokened HLS stream. Real new connector work on both sides,
  not attempted.
- **`../../prd.md` is still Ventura's as-written.** Its architecture (schema,
  pipeline shape, AI guardrails, phase structure) is city-agnostic and
  still applies, but anything naming specific Ventura agencies/geography by
  name is stale — see the repo root's `OVERVIEW.md`.

## Running it

```bash
cp .env.example .env
docker compose up -d postgres
docker compose run --rm api python scripts/init_db.py
docker compose run --rm api python scripts/seed_sources.py
docker compose run --rm api python scripts/seed_prompts.py
docker compose up -d api worker
```

Dashboard: http://localhost:8012 (mapped from container port 8000; offset
from Ventura Civic Radar's 8010 so both stacks can run on the same host at
once — see `docker-compose.yml` if you'd rather change it).

API docs: http://localhost:8012/docs

The worker starts fetching immediately (any source with `last_fetched_at IS
NULL` is due right away) and re-polls per `polling_interval_minutes`. Watch it
with `docker compose logs -f worker`. With zero sources seeded, there's
nothing for it to do yet — that's expected until the TODO list above is
worked through.

### Local AI (optional but recommended)

```bash
docker compose up -d ollama
docker compose exec ollama ollama pull llama3.1:8b
docker compose exec ollama ollama pull nomic-embed-text
```

Model names are configured via `OLLAMA_TRIAGE_MODEL` / `OLLAMA_ANALYSIS_MODEL`
/ `OLLAMA_EMBEDDING_MODEL` in `.env` — set them to whatever you've actually
pulled. Without Ollama running, classification still works via the heuristic
fallback (everything it produces is marked `confidence: low` and
`human_review_required: true`, so it always lands in the review queue rather
than being trusted outright). This stack's Ollama container is on host port
11435 (offset from Ventura's 11434) — consider pointing both projects at one
shared Ollama instance instead of running two, to avoid duplicating
multi-GB model downloads.

### Meeting-audio transcription (optional, not currently usable)

See `whisperx_service/README.md` and "Known gaps" above — no working Santa
Cruz meeting-audio source has been found yet (county's podcast feed is
empty; both county and city video streams are CloudFront-gated), so there's
nothing to deploy against.

### Running tests

`docker compose run --rm api pytest` (add `--cov=app --cov-report=term-missing`
for a coverage report). Tests run against a real `civic_radar_test` Postgres
database (created automatically on first run) — not sqlite, since several
models depend on Postgres-only features (pgvector's `Vector`/
`cosine_distance`, JSONB). Each test runs inside a transaction rolled back
afterward for isolation; see `../../core/tests/conftest.py`'s
`join_transaction_mode="create_savepoint"` comment for why that's needed
(application code under test calls `db.commit()`/`db.rollback()` for real).

567 tests, 100% coverage on both new connector modules
(`test_onbase_agenda.py`, `test_scc_planning_search.py`) as of 2026-07-10 —
the 535 inherited from Ventura at fork time, plus 32 new tests for the two
Santa-Cruz-specific connectors. Same `AGENCY_CONFIG`-dependent crime-data
test adjustments as at fork time (see `../../core/tests/test_crime_data.py`,
`../../core/tests/conftest.py`). Re-run after making any further changes to confirm
nothing regressed.

### Re-running database setup

`init_db.py`, `seed_sources.py`, and `seed_prompts.py` are all idempotent —
safe to re-run after pulling schema/prompt changes.

### Manually ingesting a document from a blocked source

For a source that turns out to be bot-walled (Ventura's Elections page sat
behind an AWS WAF challenge, for example) or otherwise needs a human to
fetch it in a real browser: drop the file under
`./archive/_manual_incoming/` on the host (bind-mounted to
`/archive/_manual_incoming/` in the container), then:

```bash
docker compose run --rm api python scripts/ingest_manual_document.py \
  --source "<source name substring>" \
  --file /archive/_manual_incoming/some_notice.pdf \
  --document-type notice \
  --title "..." \
  --original-url "https://..."
```

For a batch, write a CSV manifest instead — columns `file,title,document_type`
plus optional `meeting_date,original_url` (paths relative to the manifest's
own directory unless absolute):

```bash
docker compose run --rm api python scripts/ingest_manual_document.py \
  --source "<source name substring>" --manifest /archive/_manual_incoming/manifest.csv
```

`--source` matches by case-insensitive substring against `Source.name` (must
match exactly one — so at least one real source needs to be seeded first).
This hashes/archives the file and creates a `Document` row exactly like an
automated fetch would (same dedup-by-hash, same archive path convention) —
it then gets parsed/classified/embedded/matched/alerted automatically on the
worker's next tick. Re-running with the same file is a no-op
(content-hash dedup).

## Project layout

The engine (everything below) lives in `../../core/` and is shared with
Ventura and Boston — see the repo root's `OVERVIEW.md` for the full module
map. This directory (`cities/santa_cruz/`) holds only what's actually
specific to this deployment:

```
cities/santa_cruz/
  seed_sources.py      the source registry (8 real Santa Cruz sources, see above) —
                        bind-mounted into the container over ../../core/scripts/seed_sources.py
  docker-compose.yml    builds against ../../core; Santa Cruz's ports/DB name/env vars
  .env.example, README.md (this file), CLAUDE.md
  tests/
    test_onbase_agenda.py       City of Santa Cruz agendas (Hyland OnBase, bespoke session flow)
    test_scc_planning_search.py County Planning Commission (legacy ASP search tool, bespoke session flow)

../../core/app/ingestion/
  onbase_agenda.py, scc_planning_search.py   the bespoke connectors themselves (shared module,
                                              only exercised here because seed_sources.py above
                                              references their fetch_method)

../../whisperx_service/    standalone meeting-audio transcription service (not usable here yet -- see Known gaps)
./archive/                raw archived source material (gitignored) -- created on first run
```

See `CLAUDE.md` for architecture notes aimed at future coding-agent sessions,
and `../../prd.md` for the full product requirements this build follows
(written for Ventura originally — re-check anything geography/agency-specific
before treating it as gospel for this instantiation).
