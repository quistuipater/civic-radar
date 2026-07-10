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
scaffolded for Boston, MA but not yet pointed at any real Boston sources.**
The engine below (ingestion connectors, parsing, AI layer, dashboard,
alerting) is generic and already works end-to-end against Ventura and, as of
2026-07-10, Santa Cruz (`../santa_cruz_civic_radar`) — what's missing here is
Boston-specific *configuration*: real source URLs, agency names, and
possibly new connector code if Boston's platforms turn out to differ from
what's already been seen. See "TODO: Boston source research" below for
exactly what's left, and the Santa Cruz fork for a worked example of what
that research + build process looks like end to end (2 of its 6 source
categories needed genuinely new connectors, the rest were pure
configuration).

**Massachusetts's civic-government structure differs from California's in
ways that matter for source research** — see the TODO section below before
assuming the CA-shaped category boundaries (e.g. "county campaign finance vs.
city campaign finance") translate directly. Boston is a consolidated
city/county government (Suffolk County has had no independent elected county
government since 1999), and campaign finance disclosure in Massachusetts is
administered by the state's Office of Campaign and Political Finance (OCPF),
not county-level filing officers the way NetFile-based sources have been in
both prior forks.

## What's implemented (generic engine, carried over from Ventura Civic Radar)

- **Source registry**: `backend/scripts/seed_sources.py` currently seeds
  **zero sources** — see the TODO section below. The `Source` model/registry
  itself (jurisdiction, agency, fetch method, polling interval, authority
  level) is unchanged from Ventura's and ready to receive real entries.
- **Ingestion connectors** (all generic, not Ventura-specific — each just
  needs a real URL/config to point at, though Boston may need new connector
  code the way Santa Cruz's City of Santa Cruz agendas and County Planning
  Commission sources did):
  - `app/ingestion/connectors/civicplus_agenda_center.py` — works against
    any CivicPlus AgendaCenter site (accordion-structured agenda/minutes
    listing).
  - `app/ingestion/connectors/primegov.py` — calls PrimeGov's open public
    JSON API directly for any `*.primegov.com` portal (no headless browser
    needed). Both Ventura County and Santa Cruz County use this platform for
    their Boards of Supervisors — worth checking whether Boston City
    Council does, though Boston more commonly appears (per public record,
    not yet verified live for this fork) to use Granicus's own Legislative
    Information Center rather than PrimeGov.
  - `app/ingestion/connectors/netfile_rss.py` — reads NetFile's
    unauthenticated RSS filing feed for a given agency code (Ventura
    County's is `VCO`; Santa Cruz has both a county code `SCCO` and a
    separate city code `CRUZ`). Massachusetts campaign-finance disclosure
    goes through OCPF, not county/city NetFile portals — check OCPF's own
    platform and API/RSS surface (if any) before assuming this connector
    applies at all.
  - `app/ingestion/connectors/generic.py` — generic HTML/PDF-link harvester,
    a reasonable default for any page that isn't one of the above platforms.
  - `app/ingestion/arcgis_feature_service.py` + `app/ingestion/crime_data.py`
    — syncs any public, unauthenticated ArcGIS FeatureServer (common for
    police-department open-data crime dashboards) into a dedicated
    `crime_incidents` table. `AGENCY_CONFIG` in `crime_data.py` is currently
    empty — see that file's docstring for the field-mapping pattern to
    follow once a real FeatureServer is found. Boston Police Department
    publishes a well-known "Crime Incident Reports" open dataset on Analyze
    Boston — verify live whether it's actually ArcGIS-FeatureServer-shaped
    (what this connector handles) or a different open-data platform
    (Socrata/CKAN are both common for city-run open-data portals and would
    need different connector code entirely).
  - `app/ingestion/meeting_audio.py` + `whisperx_service/` — polls a
    Granicus podcast RSS feed for meeting audio and transcribes it with
    speaker diarization via a standalone WhisperX service. Boston City
    Council's meeting archive is commonly hosted on Granicus (verify live),
    but Santa Cruz's experience is a caution here: its county Granicus
    instance's podcast feed turned out to be unpopulated (zero items)
    despite 200+ real video recordings existing, and its actual video
    stream was CloudFront-gated — check whether Boston's podcast feed
    actually has real enclosure items before assuming this connector works
    as-is. See `whisperx_service/README.md` for what NOT to reuse from the
    existing Ventura deployment if you do wire this in.
  - Every fetch archives a raw page snapshot first, regardless of what else
    it finds.
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

## TODO: Boston source research

Nothing below is wired in yet. This mirrors the categories Ventura Civic
Radar (and, since, Santa Cruz Civic Radar) ended up with after their own
source-discovery passes — use it as a checklist, not a guarantee any of
these platforms are actually what Boston uses. Budget real time for this:
Santa Cruz's pass found that only 2 of its 6 source categories were pure
"seed the URL" wins — the rest needed genuinely new connector code because
the real platform differed from what CivicPlus/PrimeGov/NetFile/ArcGIS
already handle.

- [ ] **City of Boston council/committee agendas** — identify the platform.
      Boston City Council's meeting archive is commonly associated with
      Granicus (which would also cover meeting audio/video, see below), but
      verify live rather than trusting public record — Santa Cruz's own
      county Planning Commission turned out to be on a completely different,
      much older platform than its Board of Supervisors despite both being
      county bodies, so don't assume consistency across Boston's own bodies
      either.
- [ ] **Local police open crime data** — Boston Police Department publishes
      a well-known "Crime Incident Reports" dataset on Analyze Boston
      (data.boston.gov or analyzeboston.com — verify current URL). Check
      whether it's actually ArcGIS FeatureServer-shaped (what
      `app/ingestion/crime_data.py` and `arcgis_feature_service.py` handle)
      or a Socrata/CKAN-style open-data platform, which would need different
      connector code entirely. If ArcGIS-shaped, add an `AGENCY_CONFIG`
      entry — but verify any `created_date`-like field actually varies per
      row and filters correctly via `where` before trusting it as an
      incremental-sync cursor (Ventura's didn't; this was a real live bug).
- [ ] **Campaign finance / disclosure filings** — Massachusetts uses OCPF
      (Office of Campaign and Political Finance) at the state level, not
      county filing officers. Identify OCPF's actual publishing platform and
      whether it exposes an RSS/API surface before assuming
      `netfile_rss.py` applies — it's NetFile-specific and won't work
      against a different platform without real adaptation.
- [ ] **Elections office** notices/candidate filings (Massachusetts
      Secretary of the Commonwealth's elections division, and/or Boston's
      own Election Department).
- [ ] **Meeting audio/video** — check whether Boston City Council's Granicus
      instance (if it uses one) actually has a *populated* podcast RSS feed
      before assuming `app/ingestion/meeting_audio.py` works as-is — Santa
      Cruz's county Granicus instance had 200+ real video recordings but a
      completely empty podcast feed, and its video stream turned out to be
      CloudFront-gated and not pursued. Decide whether to point at the
      existing Ventura WhisperX deployment or stand up a separate one (see
      `whisperx_service/README.md` for what not to collide with).
- [ ] Revisit `prd.md` for anything written specifically around Ventura's
      geography/agencies that should be generalized or re-scoped for Boston
      before treating it as the authoritative spec for this fork.

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

This is the same test suite Ventura Civic Radar had at fork time (536 tests,
~99% coverage, including the NUL-byte parsing fix), with `AGENCY_CONFIG`-
dependent crime-data tests and a couple of fixture defaults updated to not
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
