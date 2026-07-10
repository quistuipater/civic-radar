# Boston Civic Radar

Phase 0 prototype of the local-first civic intelligence system described in
`prd.md`. It archives government sources (agendas, staff reports, notices),
extracts and classifies them, tracks them as "issues" over time, and
generates reviewable alerts and Markdown briefs — all runnable on a single
Docker Compose stack.

**Core principle: archive first, interpret second, publish third.** Nothing is
summarized or classified without the raw source material being hashed and
saved to `/archive` first.

**This repo is a fork of [Ventura Civic Radar](../ventura_civic_radar),
brought to partial operational status for Boston, MA on 2026-07-10.** The
engine (ingestion connectors, parsing, AI layer, dashboard, alerting) is
generic and already works end-to-end against Ventura and, as of the same
day, Santa Cruz (`../santa_cruz_civic_radar`). **4 real Boston sources are
seeded and ingesting live**, verified against a real end-to-end run: City of
Boston City Council agendas/minutes (Legistar), Boston Police Department
crime incidents (ArcGIS), Massachusetts OCPF campaign-finance filings for
the Mayor and City Council, and Elections-department public notices. One
source category remains open — see "Known gaps" below, investigated and
confirmed rather than unstarted.

**Massachusetts's civic-government structure differs from California's in
ways that shaped this research** — Boston is a consolidated city/county
government (Suffolk County has had no independent elected county government
since 1999), so there's no county-layer source category the way every CA
fork has had one; and campaign finance disclosure runs through the state's
Office of Campaign and Political Finance (OCPF) rather than county-level
filing officers the way NetFile-based sources have served both prior forks.

## What's implemented

**Real Boston sources (2026-07-10, verified via a real end-to-end ingestion run):**
- **City of Boston City Council — Legistar** (`app/ingestion/legistar.py`,
  new module). Legistar (Granicus's legislative management system), not
  CivicPlus/PrimeGov — a real, documented, unauthenticated REST/OData API
  (`webapi.legistar.com`), agenda/minutes PDFs are plain permanent URLs on
  `boston.legistar1.com` with no session-state dance needed, simpler than
  OnBase. Scoped to City Council (`BodyId=138`); Legistar also hosts every
  other Boston body (Zoning Board of Appeal, School Committee, etc.) on the
  same platform but those aren't seeded — School Committee specifically is
  excluded per this project's Phase 1 school-board boundary. Live run:
  **101 new agenda/minutes documents, 58 meetings**, correctly linked.
- **Boston Police Department — Crime Incident Reports** (pure config, no new
  code — `app/ingestion/crime_data.py`'s `AGENCY_CONFIG`). Genuinely
  ArcGIS-FeatureServer-shaped, same platform as Ventura PD's feed. `OBJECTID`
  (not the more natural-looking `INC_NUM`, which repeats across one
  incident's multiple offense rows — verified live) is the identity field;
  `REPORT_DATE` was verified as a real incremental-sync cursor. Live run (a
  first full sync, since there was no prior cursor): **330,012 incidents**.
- **Massachusetts OCPF — Boston Mayor & City Council Filings**
  (`app/ingestion/connectors/ocpf.py`, new connector, but plugs into the
  existing generic `discover()`/`CONNECTORS` dispatch — no bespoke
  ingestion function needed, since OCPF's `/reports/log` is JSON, not HTML/
  RSS, but still fits the same interface as `netfile_rss.py`). OCPF runs its
  own real, documented REST API (`api.ocpf.us`, Swagger-published),
  unauthenticated. Scoped via a `BOSTON_CPF_IDS` allowlist to the Mayor + 13
  City Councilors specifically (from `GET /municipalities`), not every state
  legislator/Sheriff/DA whose district happens to overlap Boston. Known
  limitation: `/reports/log` only returns the ~50 most recent filings
  statewide with no pagination/date-range params, so a Boston filing could
  in principle be missed between polls if outpaced by other MA filings (same
  class of caveat as NetFile's rolling-window feeds elsewhere in this
  project). Live run: **1 new filing** (Mayor Wu's real, same-day deposit
  report).
- **City of Boston Public Notices — Elections**
  (`app/ingestion/connectors/boston_public_notices.py`, new connector,
  also plugs into the existing generic `discover()`/`CONNECTORS` dispatch).
  boston.gov's public-notices board (Drupal) lists every department's
  notices on one page — filtered via its own `field_contact_target_id[]=551`
  facet to Elections specifically, out of ~100 department ids the site
  exposes. Each notice is its own individually-addressed HTML page
  (`/public-notices/{id}`), not a linked PDF, so `generic.py`'s PDF harvester
  finds nothing here; this connector treats each listing link as the
  document itself and lets the generic archive/parse pipeline handle the
  `text/html` content directly (no bespoke ingestion function needed). Low
  volume by nature, not a sign of a broken connector. Live run: **1 new
  notice** ("Board of Election Commissioners Meeting").

**Generic engine (carried over from Ventura Civic Radar, unchanged):**
- **Ingestion connectors**, reusable by any future source without new code:
  - `app/ingestion/connectors/civicplus_agenda_center.py` — CivicPlus
    AgendaCenter sites (accordion-structured agenda/minutes listing). Not
    used by Boston's real sources above.
  - `app/ingestion/connectors/primegov.py` — PrimeGov's open public JSON
    API. Both Ventura County and Santa Cruz County use this for their
    Boards of Supervisors; Boston uses Legistar instead (verified live).
  - `app/ingestion/connectors/netfile_rss.py` — NetFile's unauthenticated
    RSS filing feed, used by Ventura and Santa Cruz. Not applicable to
    Massachusetts (see OCPF above).
  - `app/ingestion/connectors/generic.py` — generic HTML/PDF-link harvester,
    fallback for any page that isn't one of the above platforms.
  - `app/ingestion/arcgis_feature_service.py` + `app/ingestion/crime_data.py`
    — syncs any public, unauthenticated ArcGIS FeatureServer into a
    dedicated `crime_incidents` table; now configured for Boston PD, see
    above.
  - `app/ingestion/meeting_audio.py` + `whisperx_service/` — polls a
    Granicus podcast RSS feed for meeting audio and transcribes it with
    speaker diarization via a standalone WhisperX service. Boston's
    Granicus podcast feed (`boston.granicus.com`) is genuinely populated
    (unlike Santa Cruz's empty one) — but see "Known gaps" below for why
    this isn't wired in.
  - Every fetch archives a raw page/response snapshot first, regardless of
    what else it finds.
- **Parsing**: PDF (via `pdfplumber`) and HTML text extraction, page-level
  chunking, and regex-based structured field extraction (ordinance/resolution/
  project numbers, APNs, comment deadlines, public hearing dates). Pages with
  no embedded text (scanned/image-only) fall back to OCR (`pytesseract` +
  `pdf2image`/poppler) automatically, page by page. An OCR-attempts cap and a
  120s wall-clock parse budget keep pathological inputs (Santa Cruz's fork
  hit a real 900+ page City Council budget packet) from taking down the
  worker. Extracted text is sanitized of embedded NUL bytes before storage —
  a real bug found via that same 900+ page packet (Postgres TEXT columns
  reject `\x00` outright); fixed upstream in both Ventura and Santa Cruz,
  and this fork inherits the fix.
- **AI layer**: a local Ollama client for classification, document
  summarization, chunk embeddings (`nomic-embed-text`), agenda-item
  extraction, and meeting-results extraction (what *actually happened* at a
  meeting, distinct from what was proposed), with a deterministic
  keyword/date heuristic fallback for classification when Ollama is
  unreachable — the pipeline never blocks on the model server being down
  (see `backend/app/ai/`). Prompts are versioned in the `prompts` table and
  already reference "Boston Civic Radar" rather than Ventura's or Santa
  Cruz's name. **Model note carried over from Ventura**: `gpt-oss:20b`
  produced garbled/incoherent output when tested against `madhatter.local`
  — `OLLAMA_TRIAGE_MODEL`/`OLLAMA_ANALYSIS_MODEL` default to `llama3.1:8b`;
  re-verify before changing either, especially if pointing at a different
  Ollama instance than Ventura's.
- **Semantic search**: `document_chunks.embedding` (pgvector) is populated
  automatically as documents are parsed; `/api/search` returns pgvector
  cosine-similarity matches (`semantic_matches`) alongside keyword results.
- **Issue tracking**: manual issue creation via API/dashboard, high-confidence
  auto-linking of documents to issues by exact project/ordinance/resolution
  number match, and a Markdown issue brief exporter matching the format in
  `prd.md` section 28. Fuzzy semantic candidates are available at
  `GET /api/documents/{id}/suggested-issues` for a human to confirm —
  deliberately **not** auto-linked (see `app/issue_matching.py` for why an
  auto-link version was tried and rejected on Ventura's real corpus).
- **Daily digest** (`prd.md` 9.9.4): `/digest` in the dashboard, or
  `GET /api/digest/daily.md` for a Markdown export. Seven sections — top
  changes, upcoming hearings/votes, new public notices, new campaign/election
  items, items needing human review, approaching deadlines, low-confidence/
  unverified claims.
- **Meeting-results extraction**: `app/ai/meeting_results.py` summarizes what
  *actually happened* at a meeting from its `minutes` document, distinct from
  the generic `document_summary` prompt (which is framed around *proposed*
  decisions, the wrong shape for a document reporting a decision already
  made). Also handles "Approval of the Minutes" items specifically, which
  approve *prior* meetings' minutes named in the item's own free-text
  description rather than the current meeting's own minutes.
- **Connector health tracking**: every `Fetch` row records `items_found`,
  `validation_status` (`ok`/`empty`/`schema_mismatch`/`error`), and
  `validation_message` — catches "fetch succeeded but the data looks wrong"
  cases a plain HTTP-status check misses.
- **Alerts**: levels 1-4 per `prd.md` 9.12, deduplicated per document+level.
- **Dashboard**: server-rendered (Jinja2, no build step) — home, review
  queue, sources, issues, meeting/document/transcript detail, manual
  submission form.
- **REST API**: FastAPI, routes per `prd.md` section 17.
- **Test suite**: pytest — see "Running tests" below for current counts.
  Fixture defaults (`tests/conftest.py`) use "City of Boston" rather than
  Ventura's jurisdiction name, but most individual tests exercise generic
  logic and don't depend on the actual city name.

## Known gaps

Investigated and confirmed live 2026-07-10, not just unstarted:

- **Meeting audio.** Boston's Granicus podcast feed
  (`boston.granicus.com/Podcast.php?view_id=1`) is genuinely populated with
  real, recent items (unlike Santa Cruz's empty one) — but the actual MP3
  enclosure URLs (`archive-video.granicus.com`) are CloudFront-gated and
  return 403 even with a matching `Referer` header, the same access-
  controlled dead end Ventura and Santa Cruz both hit on their video
  streams. Confirmed, not pursued further, consistent with this project's
  standing policy against bypassing access controls.

Revisit `prd.md` for anything written specifically around Ventura's
geography/agencies that should be generalized or re-scoped for Boston before
treating it as the authoritative spec for this fork.

## Running it

```bash
cp .env.example .env
docker compose up -d postgres
docker compose run --rm api python scripts/init_db.py
docker compose run --rm api python scripts/seed_sources.py
docker compose run --rm api python scripts/seed_prompts.py
docker compose up -d api worker
```

Dashboard: http://localhost:8013 (mapped from container port 8000; offset
from Ventura Civic Radar's 8010 and Santa Cruz's 8012 so all three stacks
can run on the same host at once — see `docker-compose.yml` if you'd rather
change it).

API docs: http://localhost:8013/docs

The worker starts fetching immediately (any source with `last_fetched_at IS
NULL` is due right away) and re-polls per `polling_interval_minutes`. Watch
it with `docker compose logs -f worker` — with the 3 real sources above
seeded, it has real work to do from the first tick.

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
11436 (offset from Ventura's 11434 and Santa Cruz's 11435) — consider
pointing all three projects at one shared Ollama instance instead of running
three, to avoid duplicating multi-GB model downloads.

### Meeting-audio transcription (optional)

Not a Docker Compose service — it needs a real GPU with meaningful VRAM
headroom, so it runs standalone on a GPU host rather than being passed
through into a container, same reasoning as Ollama. No Boston meeting-audio
source has been identified yet, so there's nothing to deploy until the TODO
list above turns one up. See `whisperx_service/README.md` for what NOT to
reuse from the existing Ventura deployment if you do wire one in.

### Running tests

`docker compose run --rm api pytest` (add `--cov=app --cov-report=term-missing`
for a coverage report). Tests run against a real `civic_radar_test` Postgres
database — created automatically on first run — not sqlite, since several
models depend on Postgres-only features (pgvector's `Vector`/
`cosine_distance`, JSONB). Each test runs inside a transaction that's rolled
back afterward for isolation.

561 tests, ~99% coverage: 536 inherited from Ventura at fork time (including
the NUL-byte parsing fix) plus 25 new for the three Boston-specific
connectors (`tests/test_legistar.py`, `tests/test_connectors.py`'s
`TestOcpfDiscover` and `TestBostonPublicNoticesDiscover`), all at 100%
coverage on the modules themselves. `AGENCY_CONFIG`-dependent
crime-data tests and a couple of fixture defaults were updated to not
assume a real Ventura agency/jurisdiction is configured (see
`tests/test_crime_data.py`, `tests/conftest.py`) — the same adjustment
already made for Santa Cruz's fork, copied directly since the underlying
problem is identical. Re-run after making any Boston-specific changes to
confirm nothing regressed.

### Re-running database setup

`init_db.py`, `seed_sources.py`, and `seed_prompts.py` are all idempotent —
safe to re-run after pulling schema/prompt changes.

### Manually ingesting a document from a blocked source

For a source that turns out to be bot-walled or otherwise needs a human to
fetch it in a real browser: drop the file under `./archive/_manual_incoming/`
on the host (bind-mounted to `/archive/_manual_incoming/` in the container),
then:

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
whisperx_service/          standalone meeting-audio transcription service (not yet deployed for Boston)
archive/                  raw archived source material (gitignored)
```

See `CLAUDE.md` for architecture notes aimed at future coding-agent sessions,
and `prd.md` for the full product requirements this build follows (written
for Ventura originally — re-check anything geography/agency-specific before
treating it as gospel for this fork).
