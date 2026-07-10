# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Current State

**This is a fork of Ventura Civic Radar, brought to partial operational status for Boston, MA on 2026-07-10.** The engine (FastAPI + SQLAlchemy + Jinja2 dashboard + a Python worker as the ingestion scheduler, orchestrated via `docker-compose.yml`: postgres/pgvector, ollama, api, worker) is unchanged from Ventura's working Phase 0 build. **3 real Boston sources are seeded and ingesting live**: City Council agendas/minutes via Legistar (`app/ingestion/legistar.py`, a new bespoke module — Legistar is a real, documented, unauthenticated REST/OData API, not CivicPlus/PrimeGov), Boston PD crime incidents via ArcGIS (pure `AGENCY_CONFIG` addition to `app/ingestion/crime_data.py`, no new code), and Massachusetts OCPF campaign-finance filings for the Mayor + City Council (`app/ingestion/connectors/ocpf.py`, a new connector that plugs into the existing generic `discover()`/`CONNECTORS` dispatch since OCPF's `/reports/log` is JSON, not HTML/RSS). A real end-to-end run produced 101 new Legistar documents across 58 meetings, 330,012 crime incidents (first full sync), and 1 real OCPF filing. Two categories remain open, both investigated and confirmed rather than unstarted (see README.md's "Known gaps"): elections/candidate-filing notices (boston.gov/public-notices is real but serves individually-addressed HTML pages, not linked PDFs, so the generic connector doesn't apply) and meeting audio (Boston's Granicus podcast feed is genuinely populated, unlike Santa Cruz's, but the MP3s are CloudFront-gated and 403 even with a matching Referer header). Note: `gpt-oss:20b` produced garbled output on `madhatter.local` when tested from Ventura Civic Radar (MXFP4/kernel issue) — `OLLAMA_TRIAGE_MODEL`/`OLLAMA_ANALYSIS_MODEL` are pinned to `llama3.1:8b` until that's debugged; re-verify if pointing at a different Ollama instance. A standalone WhisperX transcription service (`whisperx_service/`) exists as scaffolding only; not deployed, since the meeting-audio gap above means there's nothing to transcribe yet.

Common commands:
- `docker compose up -d postgres && docker compose run --rm api python scripts/init_db.py` — create schema
- `docker compose run --rm api python scripts/seed_sources.py && docker compose run --rm api python scripts/seed_prompts.py` — seed source registry (3 real Boston sources) + versioned prompts (both idempotent)
- `docker compose up -d api worker` — dashboard at `http://localhost:8013` (offset from Ventura's 8010 and Santa Cruz's 8012 so all three stacks can run on one host), API docs at `/docs`
- `backend/tests/`: `docker compose run --rm api pytest`. 554 tests (536 inherited from Ventura at fork time + 18 new for the two Boston-specific connectors, both at 100% coverage), ~99% overall. Runs against a real `civic_radar_test` Postgres database (not sqlite — several models need pgvector/JSONB), each test isolated in a rolled-back transaction (see `join_transaction_mode="create_savepoint"` in `tests/conftest.py` — required since app code calls `db.commit()` for real; `db_session_factory` exposes the same sessionmaker directly for code like `worker.py` that opens its own `SessionLocal()` rather than taking a `db` param). Re-run after any Boston-specific change to confirm nothing regressed.

Follow the existing stack and module layout in `backend/app/` rather than introducing a different framework or reorganizing — it mirrors the PRD's architecture directly (see below). Legistar and OCPF needed genuinely new ingestion code because Boston's real platforms differ from every one this project had seen in CA; crime data was a pure-config win. Check `README.md`'s "What's implemented" section before assuming a Boston capability doesn't exist yet — two real ones do.

## What This Project Is

Boston Civic Radar is a local-first civic intelligence system that monitors official City of Boston / Massachusetts government sources (agendas, staff reports, public notices, campaign filings) and turns them into tracked, source-linked "issues" with timelines, deadlines, and reviewable AI summaries. Full detail lives in `prd.md` — read it before implementing any feature; the summary below only covers what recurs across the design and would otherwise require reading the whole document to piece together. **Note**: `prd.md` was written for Ventura Civic Radar and inherited as-is into this fork — its architecture (schema, pipeline shape, AI guardrails, phase boundaries) is city-agnostic and still applies, but anything mentioning specific Ventura agencies/geography by name is stale and should be re-scoped for Boston before being treated as a real requirement. Massachusetts's civic-government structure also differs from California's in ways that affect scoping, not just naming — no independent Suffolk County government since 1999, OCPF instead of county filing officers (see "Current State" above) — before assuming CA-shaped category boundaries translate directly.

### Core Product Principle

**Archive first. Interpret second. Publish third.** Raw source material (HTML, PDFs, metadata) must be durably archived before any parsing, classification, or summarization happens. The AI layer is an analytical assistant, not the system of record — nothing should overwrite or bypass the raw archive.

### Target Deployment

- Runs on `madhatter`, a local Debian server/workstation (Docker Compose, NVIDIA GPU, ~16GB VRAM, ~32GB RAM).
- Local-first: core product must not depend on cloud inference. Cloud AI is an optional manual escalation path only, never a default dependency.
- Dashboard is LAN-only in Phase 1 — no public exposure, minimal auth is acceptable until that changes.

## Intended Architecture

Pipeline shape (see `prd.md` §7–8, §10.2 for full diagrams):

```
Official sources → n8n scheduled fetch → raw archive (HTML/PDF/metadata)
  → document parsing (text + page/section structure)
  → structured extraction (dates, project numbers, entities, deadlines)
  → embeddings (pgvector) + AI classification/summarization
  → issue clustering (match to existing issue or create new one)
  → alert scoring → human review queue → dashboard / publishing export
```

Implemented containers (`docker-compose.yml`): `postgres` (pgvector image), `ollama`, `api` (FastAPI + the server-rendered dashboard in one process), `worker` (Python scheduler — see "Current State" above for why this stands in for n8n). `redis`/`minio`/`prometheus`/`grafana` are not implemented; add them only if a concrete need shows up.

### Central domain objects

- **Source** — a monitored URL/feed with jurisdiction, agency, fetch method, polling interval, authority level (official/media/advocacy/social/manual-unverified).
- **Document** — an archived, hashed (SHA-256) artifact tied to a source and fetch; parsed into `document_chunks` for embeddings.
- **Meeting** / **Agenda Item** — structured representation of a public meeting and its individual agenda entries (action type, vote/hearing flags, consent calendar flag).
- **Issue** — the *central product object*: a civic matter that persists and evolves across meetings/documents over time (e.g. "Downtown parking ordinance"). Has status, importance/urgency/controversy/transparency-risk/financial/legal scores.
- **Issue Event** — any dated occurrence attached to an issue (notice posted, hearing scheduled, vote taken, appeal filed, etc.), always with a source link and confidence level.
- **Alert** — generated from issue/agenda-item changes, leveled 1 (Captured) through 4 (High Impact/Imminent).
- **ai_outputs** — every AI-generated classification/summary is stored with its prompt version and model name, kept separate from source-of-truth fields, and never overwrites raw records.

The full Postgres schema (sources, fetches, documents, document_chunks, meetings, agenda_items, issues, issue_events, issue_links, entities, entity_mentions, alerts, ai_outputs) is defined in `prd.md` §11 — use it as the reference schema rather than redesigning tables from scratch.

### AI Guardrails (non-negotiable when implementing AI features)

- Distinguish source facts from AI inference in every stored/displayed output.
- Never assert corruption, illegality, bad faith, or named-individual allegations unless directly source-supported; these categories always require human review before publication (`prd.md` §10.4, §18.2).
- Treat social/community submissions (Nextdoor, Facebook, X) as unverified signals only — never authoritative — until confirmed against an official source.
- Preserve uncertainty and low-confidence flags rather than smoothing them over; never fabricate missing source links.
- Nothing reaches "approved for publication" status without human review, regardless of AI confidence.

### Phase boundaries

Phase 1 (current target) is scoped to City of Ventura + selected Ventura County sources (Board of Supervisors, Planning Commission, RMA, Elections/NetFile). Do not expand source coverage to other cities, school boards, water districts, LAFCo, etc. (Phase 2) or build public-facing subscription/publishing features (Phase 3) unless explicitly asked — see `prd.md` §6 and §23 for the phase definitions and exit criteria.
