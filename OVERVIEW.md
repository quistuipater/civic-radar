# Civic Radar — Platform Overview

*This repository **is** the Civic Radar platform: one shared engine (`core/`)
plus three thin per-jurisdiction instantiations (`cities/ventura/`,
`cities/santa_cruz/`, `cities/boston/`). It was reorganized in 2026-07 from
three independent forks (`ventura_civic_radar`, `santa_cruz_civic_radar`,
`boston_civic_radar`) into this monorepo, with full commit history from all
three preserved (see "History" below). This document describes the platform
as a whole; each city's own `cities/<city>/README.md` covers just what's
actually specific to that deployment.*

## Purpose

Civic Radar watches official government sources for a jurisdiction — meeting
agendas, staff reports, public notices, campaign-finance filings, sometimes
crime incidents — and turns them into a tracked, searchable record of civic
activity. Instead of manually checking a dozen agency websites for what's
coming up or what just changed, it ingests those sources on a schedule,
archives the raw material, and uses local AI to classify and summarize it
into **issues**: persistent civic matters (e.g. "Downtown parking ordinance")
that accumulate timeline events, deadlines, and source-linked evidence across
multiple meetings and documents over time.

It's a local-first, single-operator tool, not a public service — in its
current phase it's meant to make one person (or a small team) faster at
noticing and following civic matters that matter to them, with a review
queue so nothing AI-generated gets treated as fact without a human looking
at it first.

## One engine, three instantiations

`core/` is the entire engine — schema, pipeline, dashboard, AI guardrails,
every ingestion connector (generic *and* bespoke). Each `cities/<city>/`
directory adds only what that jurisdiction's real government platforms
require: seed data, a `docker-compose.yml`, and — for the two cities with
genuinely different source platforms — nothing at the code level, since the
bespoke connector modules themselves already live in `core/app/ingestion/`
(they're inert unless a city's seed data references their `fetch_method`).

| | **Ventura** *(origin)* | **Santa Cruz** | **Boston** |
|---|---|---|---|
| Jurisdiction | City of Ventura + Ventura County | City of Santa Cruz + Santa Cruz County | City of Boston + Massachusetts state (OCPF) |
| Dashboard port | 8010 | 8012 | 8013 |
| City agendas platform | CivicPlus AgendaCenter (generic connector) | Hyland OnBase — bespoke, session-stateful connector (`onbase_agenda.py`) | Legistar REST/OData API — bespoke connector (`legistar.py`) |
| County/board agendas | PrimeGov (BOS + Planning Commission share one platform) | PrimeGov for BOS; a legacy classic-ASP search tool for Planning Commission — bespoke connector (`scc_planning_search.py`) | Zoning Board of Appeal via the same Legistar module as City Council (different `BodyId`) — pure config |
| Campaign finance | NetFile (generic connector) | NetFile, county (`SCCO`) + city (`CRUZ`) — 4 feeds | Massachusetts OCPF — bespoke connector (`ocpf.py`), JSON API |
| Crime data | Ventura PD + VC Sheriff via ArcGIS — `cities/ventura/city_settings.py` | Investigated, not found — city/county only publish jurisdiction-boundary layers, no incidents | Boston PD via ArcGIS — `cities/boston/city_settings.py` |
| Building permits / food inspections | Not sourced | Not sourced | Analyze Boston (`data.boston.gov`) via the CKAN Datastore API — generic `ckan_datastore.py` connector, bulk upsert |
| Elections/notices | NetFile-adjacent; bot-walled (AWS WAF) | County Elections Division (generic connector, no bot wall here) | Bespoke connector (`boston_public_notices.py`) — each notice is its own HTML page, not a linked PDF |
| Meeting audio | Working (Granicus podcast feed populated) | Not usable — county's podcast feed returns zero items, both video streams CloudFront-gated | Not usable — podcast feed *is* populated, but audio files are CloudFront-gated (403 even with matching Referer) |

The pattern across all three: **most connectors turn out to be reusable
as-is** (PrimeGov, NetFile, the generic HTML/RSS harvester) because civic
software vendors serve multiple jurisdictions. The exceptions are real
engineering, not configuration — a jurisdiction's genuinely different
platform (OnBase instead of CivicPlus, Legistar instead of PrimeGov, OCPF
instead of a county filing officer) requires a new bespoke, session-stateful
ingestion module rather than a config tweak. Each city's `README.md` and
`CLAUDE.md` document exactly which of its sources were "pure config" versus
"new code," and why.

## Design principles

These apply identically across all three instantiations — they are
properties of the platform, not of any one jurisdiction's deployment:

- **Archive first, interpret second, publish third.** Every raw document
  (HTML, PDF, metadata) is hashed and durably saved before any parsing or AI
  touches it. The archive is the system of record; AI output is always a
  secondary, clearly-labeled layer on top of it, never a replacement for it.
- **Source facts vs. AI inference, always distinguished.** Every
  AI-generated classification or summary is stored separately (`ai_outputs`),
  tagged with its prompt version and model name, and never overwrites a
  source-derived field.
- **Human review before anything is trusted.** Low-confidence output,
  unverified social/community submissions, and any claim touching
  corruption, illegality, or named-individual wrongdoing route to a review
  queue rather than being surfaced as settled fact.
- **Local-first AI.** Classification, summarization, and embeddings run
  against a local Ollama instance, shared across instantiations where
  convenient. Cloud AI is not a dependency anywhere in the default pipeline.

`prd.md` is the platform's product requirements document — architecture,
schema, pipeline shape, and phase structure are jurisdiction-agnostic and
apply to all three as written. It was originally authored for Ventura, so
anything in it naming Ventura's specific agencies or geography is a stale
artifact of where the platform started, not a requirement.
`EXPANSION_STRATEGY.md` (also at the repo root) has the reasoning behind the
"city is the real franchise unit" model this reorg follows — written before
the reorg, as the planning discussion that led to it.

## How it's implemented

```
core/                    the engine — one Python package, shared by every city
  app/
    models.py, config.py, worker.py, dashboard.py, main.py, db.py, schemas.py
    archive.py, alerting.py, scoring.py, issue_matching.py
    city_config.py         per-city structured overrides (see below) — default/fallback
    ai/                     prompts, classification, summarization, embeddings, Ollama client
    news/                   RSS retrieval + heuristic/AI classification for the news feed
    export/                 daily digest + issue brief Markdown export
    ingestion/
      pipeline.py            CONNECTORS registry (generic connectors, all cities)
      connectors/             generic.py, primegov.py, netfile_rss.py, civicplus_agenda_center.py,
                               ocpf.py, boston_public_notices.py
      onbase_agenda.py, scc_planning_search.py, legistar.py   bespoke, session-stateful connectors
      crime_data.py, arcgis_feature_service.py, meeting_audio.py
      ckan_datastore.py       generic CKAN Datastore API pager (used by building_permits.py,
                               food_inspections.py — currently Boston-only, inert elsewhere)
    parsing/, routers/, templates/    one shared template set — branding comes from Settings
  scripts/                init_db.py, seed_prompts.py, ingest_manual_document.py, backfill_*.py
  tests/                  ~35 shared test modules + conftest.py
  Dockerfile, requirements.txt, pyproject.toml
cities/
  ventura/    city_settings.py (crime AGENCY_CONFIG), seed_sources.py, docker-compose.yml,
              .env.example, README.md, CLAUDE.md, scripts/update_triage_model.py
  santa_cruz/ seed_sources.py, docker-compose.yml, .env.example, README.md, CLAUDE.md,
              tests/test_onbase_agenda.py, tests/test_scc_planning_search.py
              (no city_settings.py needed — no crime-data source exists, so core's empty
              default in app/city_config.py already matches)
  boston/     city_settings.py (crime AGENCY_CONFIG), seed_sources.py, docker-compose.yml,
              .env.example, README.md, CLAUDE.md, tests/test_legistar.py
whisperx_service/       shared standalone meeting-audio transcription service
prd.md, EXPANSION_STRATEGY.md, OVERVIEW.md, README.md    platform-level docs
```

Per-city identity flows through two mechanisms:

- **Scalar values** (`PROJECT_NAME`, `HTTP_USER_AGENT`, `OLLAMA_TRIAGE_MODEL`,
  `DATABASE_URL`, etc.) are `Settings` fields (`core/app/config.py`) set via
  environment variables in each city's `docker-compose.yml` — the same
  pattern `DATABASE_URL` already used before this reorg. Templates and AI
  prompts pull `project_name` from `Settings` rather than hardcoding a city
  name, so the one shared template set and prompt set render correctly for
  whichever city is actually running.
- **Structured data** that doesn't fit a scalar env var (right now, just
  `crime_data.py`'s per-agency ArcGIS field-mapping config) lives in
  `app/city_config.py`. `core/app/city_config.py` is the default/fallback
  (empty — matches Santa Cruz, which has no crime-data source); Ventura and
  Boston's `docker-compose.yml` bind-mount their own
  `cities/<city>/city_settings.py` over that path in the running container,
  the same way `../../core:/app` already bind-mounts the whole engine.

Every instantiation runs the same single Docker Compose stack:

- **postgres** (pgvector image) — the entire schema: sources, fetches,
  documents + chunked/embedded text, meetings, agenda items, issues, issue
  events, alerts, and versioned AI outputs.
- **ollama** — local model serving for classification, summarization, and
  embeddings.
- **api** — a FastAPI app that is *also* the dashboard: a server-rendered
  Jinja2 UI (no separate frontend build) plus the REST API, in one process.
- **worker** — a Python scheduler loop that stands in for the
  originally-planned n8n orchestration layer. Bespoke, session-stateful
  ingestors (crime data, meeting audio, and each city's bespoke connector)
  dispatch through a `BESPOKE_INGESTORS` registry in `worker.py`; adding a
  new bespoke connector for a future city means adding one line there, not
  a new `elif` branch.

Pipeline shape, source to dashboard — identical across instantiations:

```
official source → fetch → raw archive (hash + store)
  → parse (PDF/HTML text, page/section structure; scanned/handwritten pages
    fall back to Tesseract, then a local vision model for a bounded number
    of pages per document — see "OCR and human correction" below)
  → structured extraction (dates, project/ordinance numbers, deadlines)
  → embeddings + AI classification/summarization
  → issue matching (exact-identifier auto-link, or fuzzy semantic
    suggestion requiring human confirmation)
  → alert scoring (levels 1-4)
  → review queue → dashboard
```

**OCR and human correction.** Pages with no embedded text (scanned or
handwritten originals) go through `_ocr_page()` in
`core/app/parsing/extract.py`: the local vision model is tried first (not
Tesseract's own confidence score — confirmed live that Tesseract can be
88% "confident" about a completely misread handwritten page), capped at
`MAX_VISION_OCR_PAGES_PER_DOCUMENT` (3) attempts per document so a packet
with many scanned pages can't blow the parse-timeout budget; remaining OCR
pages (up to `MAX_OCR_PAGES_PER_DOCUMENT`, 40) fall back to Tesseract only.
Any document where vision OCR was used gets `needs_human_review = True` —
confirmed live that vision-model transcription can be fluently, confidently
*wrong* (a handwritten name misread as a different plausible-looking name)
in a way Tesseract's obviously-garbled output never is, so it's treated as
unverified until a human checks it. A document's detail page has a
"Correct this document" panel to fix any field or the extracted text
directly (re-chunks/re-embeds and clears the review flag), plus a
"re-run parsing from source" button to pick up a pipeline change on an
already-parsed document.

Port numbers (8010/8012/8013 for dashboard, similarly offset Postgres/Ollama
ports in each `docker-compose.yml`) are deliberately staggered so all three
stacks can run simultaneously on the same host (`madhatter`) without
colliding.

## History

This repo's history is the union of all three source repos' commit history,
merged via `git subtree` — nothing was squashed or discarded. Each source
repo's state immediately before the merge is tagged:

- `ventura-import-point`, `santa_cruz-import-point`, `boston-import-point`

`git log --follow core/app/alerting.py` (or any file that was identical
across all three at merge time) walks that file's real pre-merge history —
Ventura's copy was chosen as the canonical lineage for shared files, since
it was the origin fork point and had the most complete schema (see "adopted
superset" below). The other two cities' now-superseded copies of the same
file aren't part of `core/`'s live tree, but their commit history is still
fully present in the repo — reachable via, e.g.,
`git log santa_cruz-import-point -- backend/app/alerting.py`.

**One real behavior change happened as part of this reorg, not just a
move:** Ventura's `AiOutput.reviewed`/`operator_note` fields and the
"acknowledge AI output" dashboard route — present in Ventura but never
backported to Santa Cruz or Boston, since there was no shared code for it to
travel through — are now part of the shared schema. Santa Cruz and Boston
each need one additive migration (`init_db.py`, idempotent) to pick up the
two new nullable columns.

## How to use it

Each city is a self-contained Docker Compose project rooted at
`cities/<city>/`, building against `../../core` as its Docker context:

```bash
cd cities/santa_cruz   # or ventura, or boston
cp .env.example .env
docker compose up -d postgres
docker compose run --rm api python scripts/init_db.py
docker compose run --rm api python scripts/seed_sources.py
docker compose run --rm api python scripts/seed_prompts.py
docker compose up -d api worker
```

Dashboard: Ventura `http://localhost:8010`, Santa Cruz `:8012`, Boston
`:8013` — API docs at `/docs` on each.

**In the dashboard:**

- **Home** — recent activity across all sources (the 20 most recently
  created documents; use **Documents** for the full archive).
- **Documents** — every archived document, filterable by parser status,
  document type, jurisdiction, and needs-review, paginated. The
  comprehensive browse/search view — unlike Home's 20-item recency list or
  the Review Queue's exception-only, capped categories, this is where a
  document that aged off both of those can still be found.
- **Daily Digest** — top changes, upcoming hearings/votes, new notices,
  items needing review, approaching deadlines, in one page (also available
  as Markdown at `/api/digest/daily.md`).
- **Review Queue** — high-priority alerts awaiting approve/reject, documents
  that failed parsing, documents flagged for review because vision-model OCR
  was used on them, sources with repeated fetch failures, and unverified
  social/manual submissions.
- **Sources** — the registry of monitored feeds and their fetch health.
- **Issues** — the tracked civic matters; create one manually, watch
  documents get suggested or auto-linked to it, and export a Markdown brief
  once it's substantial.
- **Submit Manual Item** — for anything worth tracking that isn't from an
  official source (a Nextdoor post, a tip) — stored as unverified until
  corroborated.

Any document's detail page shows its original URL, its local archive path
(a clickable link to the actual archived file, served via the `/archive`
static mount in `core/app/main.py`), parser status, extracted identifiers,
AI outputs (or a button to run classification on demand — every action
button across the dashboard shows "Working…" and disables itself on click),
and linked/suggested issues.

**Local AI (recommended):**

```bash
docker compose up -d ollama
docker compose exec ollama ollama pull llama3.1:8b   # Ventura also needs qwen3:8b
docker compose exec ollama ollama pull nomic-embed-text
docker compose exec ollama ollama pull gemma4:12b    # vision OCR fallback for scanned/handwritten pages
```

Without Ollama running, classification still works via a deterministic
heuristic fallback — everything it produces is marked low-confidence and
routed to the review queue rather than trusted outright. Since all three
instantiations can share one Ollama instance on `madhatter`, consider
pointing them at the same one rather than running three separately and
tripling multi-GB model downloads.

**Tests:** `docker compose run --rm api pytest` from within a city's
directory runs `core/tests` (the ~35 shared modules) against that city's
database; each city's own `cities/<city>/tests/` holds tests for its
bespoke connector(s), if it has any.

**Remote access:** the dashboard has no authentication and is meant to stay
LAN-only for now. To let someone outside the LAN use it, put it behind a
mesh VPN (e.g. Tailscale) scoped with an ACL grant to just the host and port
it runs on, rather than exposing it to the public internet.

See each `cities/<city>/README.md` for the full city-specific command
reference, including manually ingesting a document from a source that turns
out to be bot-walled.

## Next steps

**Per-instantiation gaps:**

- **Santa Cruz** — crime data unavailable (no incident-level feed from
  either agency); meeting audio unusable (empty podcast feed, gated video).
  Phase 1 source list for Santa Cruz (which city boards/commissions, which
  county bodies beyond BOS/Planning) still needs deliberate scoping.
- **Boston** — meeting audio unusable (podcast feed *is* populated, unlike
  Santa Cruz, but the files themselves are CloudFront-gated).
- **Ventura** — Elections sits behind an active AWS WAF bot challenge; only
  a page snapshot gets archived there today rather than real filings.

**Platform-level:**

- **Run the Santa Cruz/Boston `reviewed`/`operator_note` migration** and
  confirm the acknowledge-AI-output route works end-to-end on both — it's
  new behavior for those two cities as of this reorg (see "History" above).
- **Shared Ollama contention across cities.** All three instantiations now
  point at one native Ollama instance on `madhatter` (see each city's
  `docker-compose.yml`/`.env`). Confirmed live 2026-08-22/23 that concurrent
  vision-OCR calls from multiple cities' workers can starve each other (and
  once, the Ollama service itself hung entirely — GPU idle, unresponsive to
  a trivial request — requiring a host-level `systemctl restart ollama`).
  Worth a real fix (request queuing/serialization, or per-city scheduling)
  if this keeps recurring rather than restarting the service reactively.
- **Standardize what "pure config" vs. "new connector" means** as a
  documented decision framework, now that three cities have each made this
  call independently — would make onboarding a fourth jurisdiction faster
  and more consistent.
- **Authentication**, if/when any instantiation moves beyond
  single-operator, LAN/VPN-only use — currently none exists anywhere, by
  design (Phase 1 scope for all three).
- **Re-scope `prd.md`** per jurisdiction, or maintain jurisdiction-specific
  appendices, instead of treating Ventura's original as gospel everywhere.
- Phase 2 (additional cities, school boards, water districts, LAFCo-style
  bodies) and Phase 3 (public-facing publishing/subscriptions) are
  explicitly out of scope for every instantiation until Phase 1 is solid
  there and someone decides to expand — see `prd.md` §6 and §23.
