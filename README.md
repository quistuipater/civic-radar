# Santa Cruz Civic Radar

Phase 0 prototype of the local-first civic intelligence system described in
`prd.md`. It archives government sources (agendas, staff reports, notices),
extracts and classifies them, tracks them as "issues" over time, and
generates reviewable alerts and Markdown briefs — all runnable on a single
Docker Compose stack.

**Core principle: archive first, interpret second, publish third.** Nothing is
summarized or classified without the raw source material being hashed and
saved to `/archive` first.

**This repo is a fork of [Ventura Civic Radar](../ventura_civic_radar),
scaffolded for Santa Cruz, CA but not yet pointed at any real Santa Cruz
sources.** The engine below (ingestion connectors, parsing, AI layer,
dashboard, alerting) is generic and already works end-to-end against Ventura;
what's missing here is Santa Cruz-specific *configuration* — real source
URLs, agency names, and a couple of platform-specific field mappings. See
"TODO: Santa Cruz source research" below for exactly what's left.

## What's implemented (generic engine, carried over from Ventura Civic Radar)

- **Source registry**: `backend/scripts/seed_sources.py` currently seeds
  **zero sources** — see the TODO section below. The `Source` model/registry
  itself (jurisdiction, agency, fetch method, polling interval, authority
  level) is unchanged from Ventura's and ready to receive real entries.
- **Ingestion connectors** (all generic, not Ventura-specific — each just
  needs a real URL/config to point at):
  - `app/ingestion/connectors/civicplus_agenda_center.py` — works against
    any CivicPlus AgendaCenter site (accordion-structured agenda/minutes
    listing). Worth checking if Santa Cruz's city or county uses this
    platform.
  - `app/ingestion/connectors/primegov.py` — calls PrimeGov's open public
    JSON API directly for any `*.primegov.com` portal (no headless browser
    needed). Ventura County uses this after migrating off Legistar; worth
    checking whether Santa Cruz County does too.
  - `app/ingestion/connectors/netfile_rss.py` — reads NetFile's
    unauthenticated RSS filing feed for a given county code (Ventura's is
    `VCO`). Only useful if Santa Cruz County's campaign-finance filings are
    also hosted on NetFile — check before assuming so.
  - `app/ingestion/connectors/generic.py` — generic HTML/PDF-link harvester,
    a reasonable default for any page that isn't one of the above platforms.
  - `app/ingestion/arcgis_feature_service.py` + `app/ingestion/crime_data.py`
    — syncs any public, unauthenticated ArcGIS FeatureServer (common for
    police-department open-data crime dashboards) into a dedicated
    `crime_incidents` table. `AGENCY_CONFIG` in `crime_data.py` is currently
    empty — see that file's docstring for the field-mapping pattern to
    follow once a real FeatureServer is found.
  - `app/ingestion/meeting_audio.py` + `whisperx_service/` — polls a
    Granicus podcast RSS feed for meeting audio and transcribes it with
    speaker diarization via a standalone WhisperX service. Only useful if
    local government bodies use Granicus for meeting recordings — check
    before assuming so. See `whisperx_service/README.md` for what *not* to
    reuse from the existing Ventura deployment if you do wire this in.
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
  submission form.
- **REST API**: FastAPI, routes per `prd.md` section 17.
- **Test suite**: pytest — see "Running tests" below for current counts.
  Fixture defaults (`tests/conftest.py`) use "City of Santa Cruz" rather
  than Ventura's jurisdiction name, but most individual tests exercise
  generic logic and don't depend on the actual city name.

## TODO: Santa Cruz source research

Nothing below is wired in yet. This mirrors the categories Ventura Civic
Radar ended up with after its own source-discovery pass — use it as a
checklist, not a guarantee any of these platforms are actually what Santa
Cruz uses.

- [ ] **City of Santa Cruz council/commission agendas** — identify the
      platform (CivicPlus AgendaCenter? Granicus? Legistar? something else?)
      and add a `Source` row in `backend/scripts/seed_sources.py`.
- [ ] **Santa Cruz County Board of Supervisors** agendas/minutes — same
      question; check for PrimeGov specifically since the connector already
      handles it generically.
- [ ] **Santa Cruz County Planning Commission** — may share whatever
      platform the Board of Supervisors uses (it did for Ventura).
- [ ] **Local police/sheriff open crime data** — look for a public ArcGIS
      FeatureServer; if found, add an `AGENCY_CONFIG` entry in
      `app/ingestion/crime_data.py` (verify any `created_date`-like field
      actually varies per row and filters correctly via `where` before
      trusting it as an incremental-sync cursor — Ventura's didn't).
- [ ] **Campaign finance / Statement of Economic Interests filings** —
      identify the filing platform (NetFile? something else?) before
      assuming the existing NetFile connector applies.
- [ ] **Elections office** notices/candidate filings.
- [ ] **Meeting audio/video** — check whether local bodies use Granicus; if
      so, decide whether to point at the existing Ventura WhisperX
      deployment or stand up a second one (see `whisperx_service/README.md`).
- [ ] Revisit `prd.md` for anything written specifically around Ventura's
      geography/agencies that should be generalized or re-scoped for Santa
      Cruz before treating it as the authoritative spec for this fork.

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

### Meeting-audio transcription (optional, not yet needed)

See `whisperx_service/README.md` — no Santa Cruz meeting-audio source has
been identified yet, so there's nothing to deploy until the TODO list above
turns one up.

### Running tests

`docker compose run --rm api pytest` (add `--cov=app --cov-report=term-missing`
for a coverage report). Tests run against a real `civic_radar_test` Postgres
database (created automatically on first run) — not sqlite, since several
models depend on Postgres-only features (pgvector's `Vector`/
`cosine_distance`, JSONB). Each test runs inside a transaction rolled back
afterward for isolation; see `tests/conftest.py`'s
`join_transaction_mode="create_savepoint"` comment for why that's needed
(application code under test calls `db.commit()`/`db.rollback()` for real).

This is the same test suite Ventura Civic Radar had at fork time (535 tests,
~99% coverage), with `AGENCY_CONFIG`-dependent crime-data tests and a couple
of fixture defaults updated to not assume a real Ventura agency/jurisdiction
is configured (see `tests/test_crime_data.py`, `tests/conftest.py`). Re-run
after making any Santa Cruz-specific changes to confirm nothing regressed.

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

```
backend/
  app/
    models.py            SQLAlchemy models — the schema from prd.md section 11
    ingestion/            fetch + archive + per-source connectors
    parsing/              PDF/HTML text extraction, chunking, regex field extraction
    ai/                    Ollama client, prompts, classification, summarization, heuristic fallback
    issue_matching.py     exact-identifier auto-link + fuzzy embedding suggestions (human-confirmed)
    alerting.py           alert level computation + generation
    scoring.py            alert-level thresholds (prd.md section 12)
    export/markdown.py    issue brief exporter
    routers/               REST API endpoints
    dashboard.py          server-rendered dashboard routes
    templates/             Jinja2 templates
    worker.py             scheduler loop (the "n8n stand-in" for Phase 0)
  scripts/
    init_db.py             create pgvector extension + all tables
    seed_sources.py        seed the source registry (currently empty -- see TODO above)
    seed_prompts.py         seed versioned prompt templates
whisperx_service/          standalone meeting-audio transcription service (not yet deployed for Santa Cruz)
archive/                  raw archived source material (gitignored)
```

See `CLAUDE.md` for architecture notes aimed at future coding-agent sessions,
and `prd.md` for the full product requirements this build follows (written
for Ventura originally — re-check anything geography/agency-specific before
treating it as gospel for this fork).
