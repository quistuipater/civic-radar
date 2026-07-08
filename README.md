# Ventura Civic Radar

Phase 0 prototype of the local-first civic intelligence system described in
`prd.md`. It archives real government sources (agendas, staff reports,
notices), extracts and classifies them, tracks them as "issues" over time, and
generates reviewable alerts and Markdown briefs — all runnable on a single
Docker Compose stack.

**Core principle: archive first, interpret second, publish third.** Nothing is
summarized or classified without the raw source material being hashed and
saved to `/archive` first.

## What's implemented (Phase 0 scope)

- **Source registry** seeded with 11 real, verified Ventura sources (see
  `backend/scripts/seed_sources.py`): City of Ventura AgendaCenter (all
  boards/committees), Ventura County Board of Supervisors (PrimeGov), Ventura
  County Planning Commission (PrimeGov), three more RMA hearing bodies
  (Cultural Heritage Board, Planning Director Hearings, Mobile Home Park Rent
  Review Board), Ventura County Elections, two NetFile RSS feeds (campaign
  finance filings, and Statement of Economic Interests/Form 700), and two
  crime-data feeds (Ventura PD, VC Sheriff — see "Crime incident data" below).
- **Ingestion**: a CivicPlus AgendaCenter connector that parses the real
  accordion structure of `cityofventura.ca.gov/AgendaCenter` (21 categories,
  ~210 agenda/minutes documents as of last check); a PrimeGov connector that
  calls the open public JSON API directly (`ventura.primegov.com`) for real
  agendas/packets/minutes, used by both the Board of Supervisors (committee
  id 1) and the Planning Commission (committee id 85 — the RMA source
  originally pointed at a thin landing page with ~1 real PDF link; the real
  Planning Commission hearing content turned out to be the same PrimeGov
  platform as BOS, just embedded as an iframe, verified live 2026-07-06).
  Writing tests for this connector (2026-07-08) caught a real bug: `body`
  was hardcoded to "Board of Supervisors" regardless of which committee was
  being fetched, since PrimeGov's meeting-list API has no human-readable
  committee name, only a numeric `committeeId` — silently mislabeling every
  Planning Commission document and meeting (14 documents, 8 meetings in the
  DB, corrected via a one-off UPDATE; no cross-contamination since no two
  committees' meetings ever fell on the same date). Fixed by having the
  connector take the source's own `body` as a parameter instead of
  guessing — see `app/ingestion/connectors/primegov.py` and
  `tests/test_primegov.py`; a NetFile RSS connector that reads NetFile's real-time, unauthenticated
  filing feed (`netfile.com/connect2/api/public/list/filing/rss/VCO/
  campaign.xml`) — the *interactive* NetFile portal sits behind Cloudflare
  Turnstile and we don't try to bypass that, but NetFile separately publishes
  this plain-HTTP RSS feed with no challenge at all, each item linking
  directly to the filing PDF (verified live 2026-07-06: 24 real Form
  460/470/501 filings archived on first run). Feed only covers a rolling
  window (max 15 days/1000 items per NetFile's own feed description), so it's
  for ongoing monitoring rather than historical backfill; and a generic
  HTML/PDF-link harvester for everything else, which also now covers three
  more RMA hearing bodies — Cultural Heritage Board and Planning Director
  Hearings both have real, directly-harvestable hearing-notice/staff-report
  PDFs (verified live); Mobile Home Park Rent Review Board's page is real but
  currently has zero board-specific postings (just site-wide boilerplate
  links) — kept as a source anyway per archive-first, so nothing is missed
  once it does post something. Every fetch archives a raw page snapshot
  first, regardless of what else it finds.
- **Parsing**: PDF (via `pdfplumber`) and HTML text extraction, page-level
  chunking, and regex-based structured field extraction (ordinance/resolution/
  project numbers, APNs). Pages with no embedded text (scanned/image-only,
  e.g. some closed-session minutes) fall back to OCR (`pytesseract` +
  `pdf2image`/poppler) automatically, page by page. Two safeguards keep
  pathological inputs (some County board packets run 6,000+ pages) from
  taking down the worker: an OCR-attempts cap per document, and a 120s
  wall-clock budget for the whole parse, after which the document is marked
  `parser_status=failed` with a clear error rather than hanging or OOMing.
- **AI layer**: a local Ollama client for classification, document
  summarization, chunk embeddings (`nomic-embed-text`), and agenda-item
  extraction, with a deterministic keyword/date heuristic fallback for
  classification when Ollama is unreachable — the pipeline never blocks on
  the model server being down (see `backend/app/ai/`). Prompts are versioned
  in the `prompts` table. **Model note**: `gpt-oss:20b` produced
  garbled/incoherent output when tested against madhatter (2026-07-05) —
  likely an MXFP4 quantization/kernel issue, not a prompt problem, since even
  a trivial "return this exact JSON" prompt came back as nonsense. Every
  classification/summarization silently fell back to heuristics/errors as a
  result until this was caught. `OLLAMA_TRIAGE_MODEL`/`OLLAMA_ANALYSIS_MODEL`
  both use `llama3.1:8b` now (confirmed clean output on the same server) —
  swap `gpt-oss:20b` back in only after separately confirming it produces
  coherent output on whatever Ollama instance you're pointed at.
- **Agenda-item extraction**: `app/ai/agenda_items.py` splits an `agenda`
  document's text into individual `agenda_items` rows (item number, title,
  department, action type, consent/hearing/vote flags) via the triage model,
  linked through `Meeting.agenda_document_id` (now populated at ingestion
  time — previously dead columns). No heuristic fallback; waits for a later
  run if Ollama's unavailable.
- **Semantic search**: `document_chunks.embedding` (pgvector) is populated
  automatically as documents are parsed; `/api/search` returns pgvector
  cosine-similarity matches (`semantic_matches`) alongside keyword results.
- **Issue tracking**: manual issue creation via API/dashboard, high-confidence
  auto-linking of documents to issues by exact project/ordinance/resolution
  number match, and a Markdown issue brief exporter matching the format in
  `prd.md` section 28. Fuzzy semantic candidates (via `document_chunks`
  embeddings) are available at `GET /api/documents/{id}/suggested-issues` for
  a human to confirm through the existing manual-link endpoint — deliberately
  **not** auto-linked. An auto-link version was tried and rejected: today's
  issue-linked documents are whole multi-topic meeting packets, so their
  mean-pooled embeddings are dominated by generic meeting-boilerplate rather
  than actual topic, and it fuzzy-"matched" 72/80 clearly unrelated documents
  in a live test (see `app/issue_matching.py` for detail and what would need
  to change — e.g. per-agenda-item embeddings — before revisiting auto-link).
- **Daily digest** (`prd.md` 9.9.4): `/digest` in the dashboard, or
  `GET /api/digest/daily.md` for a Markdown export. Seven sections — top
  changes, upcoming hearings/votes, new public notices, new campaign/election
  items, items needing human review, approaching deadlines, low-confidence/
  unverified claims. Pure rollup of already-generated AI outputs (no new model
  calls per digest run); internal/draft only, dashboard-only (not emailed —
  `prd.md` 25's open question #6 resolved that way since there's no email
  infra in this project). "Approaching deadlines" will stay empty until
  structured deadline extraction is implemented (`comment_deadline`/
  `public_hearing_date` on `Document` are never populated yet).
- **Crime incident data**: `app/ingestion/crime_data.py` +
  `app/ingestion/arcgis_feature_service.py` sync two agencies' public,
  unauthenticated ArcGIS FeatureServers into a dedicated `crime_incidents`
  table — structurally different from every other source (structured rows,
  not documents), so it doesn't go through the Document/parse/classify
  pipeline at all. **Both agencies do a full re-fetch + dedupe by external
  ID every poll** (no reliable incremental cursor for either, see below);
  fine at their current scale (43s/13s per poll respectively at 360min/
  1440min intervals). **Ventura PD** (`OpenData_Police_Crimes`, backing the
  city's "Community Crime Map" dashboard, verified live 2026-07-07): 84,327
  records, deduped by `GlobalID`. Originally attempted incremental sync via
  `created_date`, which turned out unreliable two independent ways (verified
  live 2026-07-08): every row shares the *exact same* `created_date` value
  (a bulk-load artifact, not a per-record "added at" timestamp), and the
  field silently fails to filter via `where` at all regardless of that —
  a `created_date > TIMESTAMP '...'` query returns the full unfiltered count
  no matter the threshold, while the identical query against
  `Incident_Date_Start` filters correctly. **VC Sheriff** (`NIBRS_Dashboard_2025`,
  a separate ArcGIS org from the City's, verified live 2026-07-08): a
  different schema entirely — no `GlobalID` (uses `FID`), no real incident
  date (only an integer `Year`), no address field at all, and no
  `created_date`-equivalent field either. Per-agency schema differences are
  handled by `AGENCY_CONFIG` in `crime_data.py` rather than assuming one
  layer's field names are universal. Esri's SQL dialect also rejects a raw
  epoch-millis date comparison (`created_date > 1751000000000` → 400
  "Invalid query parameters") — needs `TIMESTAMP 'YYYY-MM-DD HH:MM:SS'`
  literal syntax instead, and rejects `orderByFields`/`where` referencing a
  field a layer doesn't have — three real bugs hit live and fixed in this
  feature so far. Browse via `GET /api/crime-incidents` (filterable by
  `offense_category`, `beat`, `community_council`, `since`). VC Sheriff also
  has UCR (1991-2023)/Traffic/Hate Crimes/Use of Force/RIPA dashboards on
  the same platform — not yet added, FeatureServer URLs not yet traced.
- **Connector health tracking**: every `Fetch` row (one per poll, across
  both the Document-based and crime-data ingestion paths) now records
  `items_found` (documents/links/features actually discovered, distinct
  from "new" — a connector can succeed at the HTTP level while returning 0
  items if a source's page structure changed) plus `validation_status`
  (`ok`/`empty`/`schema_mismatch`/`error`) and `validation_message`. This
  catches "fetch succeeded but the data looks wrong" cases that a plain
  HTTP-status check misses entirely.
- **Alerts**: levels 1-4 per `prd.md` 9.12, deduplicated per document+level.
- **Dashboard**: server-rendered (Jinja2, no build step) — home, review queue,
  sources, issues, meeting/document detail, manual submission form.
- **REST API**: FastAPI, routes per `prd.md` section 17 (`/api/issues`,
  `/api/documents`, `/api/alerts`, `/api/review-queue`, `/api/search`,
  `/api/manual-submissions`, `/api/ai/*`, plus `/api/sources`).
- **Test suite**: pytest, 207 tests / ~74% coverage as of 2026-07-08, see
  "Running tests" below.

## Known Phase 0 gaps (by design, not oversight)

- **Elections (clerkrecorder.venturacounty.gov) sits behind an active AWS WAF
  bot challenge** (`x-amzn-waf-action: challenge`, verified live 2026-07-06).
  The page is real (candidate filing guides, vacancy notices, election
  calendars) but its content isn't reachable without solving that challenge,
  and we deliberately don't attempt to bypass it — the generic connector still
  archives a raw page snapshot every cycle (nothing is silently missed) but
  no real document discovery happens there. Flagged in the source's
  `known_limitations` field. For a human to retrieve a specific document
  themselves (in a real browser) and get it into the pipeline anyway, see
  `scripts/ingest_manual_document.py` below. (NetFile was originally in this
  same bucket — its *interactive* portal is genuinely Cloudflare-Turnstile-
  gated, but it turned out NetFile separately publishes an unauthenticated
  RSS feed of filings with no challenge at all, so
  `app/ingestion/connectors/netfile_rss.py` now harvests real filings there
  without needing a browser or manual retrieval. Board of Supervisors was a
  similar story — see the PrimeGov note above.)
- **The worker loop is a Python scheduler, not n8n** (polls sources on
  `polling_interval_minutes`, fetches, parses, classifies, matches, alerts).
  The PRD's recommended stack lists n8n, but we've deliberately decided
  against swapping it in: it would add a new service plus new internal HTTP
  endpoints just so n8n has something to call, for zero functional gain over
  the current in-process Python loop — not worth the added fragility unless
  a concrete need for n8n's UI/no-code workflow editing shows up later.

## Potential future sources (investigated 2026-07-07, not yet built)

A broader source-discovery pass turned these up. None are wired into the
pipeline yet — listed here so the investigation doesn't need repeating.

- **VC Sheriff's other dashboards** — same ArcGIS platform/org as the NIBRS
  feed already ingested (`sheriff.venturacounty.gov/transparency-dashboard/
  crime-traffic/`): 1991-2023 UCR Crime, Traffic, Hate Crimes, Use of Force,
  RIPA. Underlying FeatureServer(s) for these specific dashboards not yet
  traced (only NIBRS has been).
- **City of Ventura Granicus archive**
  (`cityofventura.granicus.com/ViewPublisher.php?view_id=2`) — has its own
  official Agenda RSS feed, but appears to cover the same City Council/
  Commission meetings already ingested via `civicplus_agenda_center`; likely
  redundant unless the video/audio archive angle becomes valuable.
- **Maven's Notebook** (`mavensnotebook.com`) — statewide California
  water-policy news aggregator, not Ventura-specific, but has a real
  "Ventura County" tag RSS feed (`mavensnotebook.com/tag/ventura-county/
  feed/`). Would be a `media`-authority-level source per prd.md's authority
  levels, and narrow (water-policy only), not general local news.
- **VC Star / VC Reporter** — no RSS feed found on VC Star (tried common
  patterns, all 404; Gannett papers have been dropping public RSS). VC
  Reporter's feed URL wasn't resolved. The `rss.feedspot.com/ventura_*`
  aggregator pages suggested weren't useful for either (one was
  podcasts-only, the other didn't surface a working feed URL).
- **Email newsletters** (e.g. `cityofventura.ca.gov/1013/Email-Newsletters`)
  — a genuinely different connector shape than everything above (event-driven
  via a mailbox, not HTTP-poll-based): would need a dedicated inbox, IMAP/
  Gmail-API polling, and an HTML-email parser feeding into the archive
  pipeline. Worth checking what a sample newsletter actually contains first
  (may just re-link content already covered by other sources) before
  building the ingestion side.
- **Public health surveillance (CDC NWSS, WastewaterSCAN, CDC NSSP, CDC
  FluView/RSV-NET)** — investigated 2026-07-08. CDC NSSP and FluView/RSV-NET
  remain ruled out: state-level only by design (confirmed via each dataset's
  schema — no county/sub-state field exists to filter on). WastewaterSCAN
  monitors 90 sites nationwide (30 in California) via a plain public CSV
  (`data.wastewaterscan.org/data/plant-points.csv`, found via browser
  network inspection of their tracker page, no API key needed) but none are
  in Ventura County (nearest: LA County/Carson, Lompoc, Ontario), and as of
  2026-07-08 they've confirmed directly (email) that they aren't onboarding
  new sites at all. Revisit specifically on/near the 1st of each month in
  case that changes (standing memory note, not automated).

  **Correction, found 2026-07-08 via CDPH's own dashboard rather than the
  public NWSS jurisdiction API/dataset**: Ventura County is *not* fully dark.
  CDPH's Cal-SuWers dashboard (`skylab.cdph.ca.gov/calwws`) lists an active
  sewershed, **"Ventura (Oxnard)"** — samples through 2026-06-30, tracking
  SARS-CoV-2, Influenza A, Influenza B, and RSV. Its `Data Source` field
  reads **"CDC NWSS Commercial Contract (Verily)"**, a reporting pathway
  distinct from the standard state/local-health-department-submitted NWSS
  sites (which is why checking NWSS's own public jurisdiction list, as
  originally done, missed it — that list apparently doesn't include
  Verily-commercial-contract sites). Two caveats before wiring this in:
  (1) the site covers **Oxnard's** treatment plant, not the City of
  Ventura's own Water Reclamation Facility, so it's county-adjacent
  coverage, not literally Ventura-city-level; (2) the dashboard is an R
  Shiny app (`#shiny-tab-download` route) with a per-sample data table
  (Region, County, County (City/Utility), Sample Date, PCR Gene Target,
  Raw Concentration, Norm PMMoV, rolling averages, Data Source — filterable
  by "County (City/Utility)" = `Ventura (Oxnard)`) and a **"Download Data"**
  button, not a plain public CSV/API endpoint like WastewaterSCAN's — the
  button is a Shiny `downloadHandler` tied to a stateful session, so a
  connector would need browser automation (e.g. Playwright driving the
  filter + click) rather than a simple HTTP GET. Not yet built; worth
  prioritizing over the three ruled-out sources above since the data
  actually exists for the county now.

## Running it

```bash
cp .env.example .env
docker compose up -d postgres
docker compose run --rm api python scripts/init_db.py
docker compose run --rm api python scripts/seed_sources.py
docker compose run --rm api python scripts/seed_prompts.py
docker compose up -d api worker
```

Dashboard: http://localhost:8010 (mapped from container port 8000 — 8000 was
already taken by something else on this machine; change the `api` port
mapping in `docker-compose.yml` if you'd rather use 8000).

API docs: http://localhost:8010/docs

The worker starts fetching immediately (any source with `last_fetched_at IS
NULL` is due right away) and re-polls per `polling_interval_minutes`. Watch it
with `docker compose logs -f worker`.

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
than being trusted outright).

### Running tests

`docker compose run --rm api pytest` (add `--cov=app --cov-report=term-missing`
for a coverage report). Tests run against a real `civic_radar_test` Postgres
database — created automatically on first run, on the same `postgres`
container as dev — not sqlite, since several models depend on Postgres-only
features (pgvector's `Vector`/`cosine_distance`, JSONB). Each test runs
inside a transaction that's rolled back afterward for isolation, so the
schema only needs to be created once per test session. The `db` fixture's
session uses `join_transaction_mode="create_savepoint"` (see
`tests/conftest.py`) — required because application code under test calls
`db.commit()`/`db.rollback()` for real (`ingest_source`, `ingest_crime_source`,
`create_alert_from_classification`, ...); without it, an inner commit ends
the fixture's own outer transaction, silently breaking isolation (caught
live 2026-07-08 via an `ObjectDeletedError` on a test that called the same
commit-triggering function twice). As of 2026-07-08:
74% overall coverage: all ingestion connectors/fetchers (94-100%), alerting/
scoring/heuristic classification (100%), and the full REST router layer
(97-100%, `tests/test_router_*.py`) — the router tests lean on the fact that
`classify_document`/`summarize_document` already degrade deterministically
with no Prompt rows seeded (heuristic fallback / 422 respectively) and
`match_document_to_issue`/`suggest_issues_for_document` are pure DB logic, so
none of that needed mocking; `search.py`'s semantic path does call
`ollama_client.embed()` with no such gate, so that one *is* explicitly
monkeypatched for determinism rather than depending on whatever
`OLLAMA_BASE_URL` happens to resolve to. Not yet covered: the AI
orchestration layer proper (`ai/pipeline.py`, `ai/agenda_items.py`, `ai/embed.py`
— needs live/mocked Ollama), OCR/parsing (needs real PDF fixtures), the
worker loop, and `issue_matching.py`'s fuzzy-suggestion path (34%, the exact
identifier auto-link is covered via the router tests).

### Re-running database setup

`init_db.py`, `seed_sources.py`, and `seed_prompts.py` are all idempotent —
safe to re-run after pulling schema/prompt changes.

### Manually ingesting a document from a blocked source

For Elections (see "Known Phase 0 gaps" above — NetFile now has an automated
RSS path and doesn't need this): download the file yourself in a real
browser, drop it under `./archive/_manual_incoming/` on the host
(bind-mounted to `/archive/_manual_incoming/` in the container), then:

```bash
docker compose run --rm api python scripts/ingest_manual_document.py \
  --source "Elections" \
  --file /archive/_manual_incoming/some_notice.pdf \
  --document-type notice \
  --title "Vacancy Notice -- District 3 Supervisor" \
  --original-url "https://clerkrecorder.venturacounty.gov/elections/..."
```

For a batch (e.g. several files at once), write a CSV manifest instead —
columns `file,title,document_type` plus optional `meeting_date,original_url`
(paths relative to the manifest's own directory unless absolute):

```bash
docker compose run --rm api python scripts/ingest_manual_document.py \
  --source "Elections" --manifest /archive/_manual_incoming/manifest.csv
```

`--source` matches by case-insensitive substring against `Source.name` (must
match exactly one). This hashes/archives the file and creates a `Document`
row exactly like an automated fetch would (same dedup-by-hash, same archive
path convention) — it then gets parsed/classified/embedded/matched/alerted
automatically on the worker's next tick, no different from anything else in
the pipeline. Re-running with the same file is a no-op (content-hash dedup).

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
    seed_sources.py        seed the Phase 1 source registry
    seed_prompts.py         seed versioned prompt templates
archive/                  raw archived source material (gitignored)
```

See `CLAUDE.md` for architecture notes aimed at future coding-agent sessions,
and `prd.md` for the full product requirements this build follows.
