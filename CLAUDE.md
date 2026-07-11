# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Current State

A working Phase 0 prototype exists under `backend/` (FastAPI + SQLAlchemy + Jinja2 dashboard + a Python worker as the ingestion scheduler), orchestrated via `docker-compose.yml` (postgres/pgvector, ollama, api, worker). It has been run end-to-end against the real City of Ventura AgendaCenter, the Ventura County Board of Supervisors'/Planning Commission's PrimeGov portals, and NetFile's public RSS filing feed — see `README.md` for setup commands, what's implemented, and known Phase 0 gaps (Elections sits behind an active AWS WAF bot challenge so only a page snapshot gets archived there today; the worker loop is a Python scheduler standing in for n8n). Note: `gpt-oss:20b` produces garbled output on madhatter (MXFP4/kernel issue) — both roles were pinned to `llama3.1:8b` until that's debugged; see README's AI layer note before changing either. As of 2026-07-11, `OLLAMA_TRIAGE_MODEL` (classification + agenda item extraction) is `qwen3:8b` instead: `llama3.1:8b` was setting `human_review_required=true` on 60-80% of documents, which turned out to be miscalibration rather than genuinely uncertain content (measured against real flagged docs, cross-checked against Claude Haiku 4.5). `qwen3:8b` lands at ~7% on the same sample with 100% valid structured JSON output, at no cost. `OLLAMA_ANALYSIS_MODEL` (summarization) is still `llama3.1:8b` — qwen3:8b hasn't been evaluated against that prompt yet. A standalone WhisperX transcription service (`whisperx_service/`, NOT a `backend/` module or a `docker-compose.yml` container — it needs direct GPU access outside Docker, same reasoning as Ollama) transcribes+diarizes Granicus meeting audio; see README's "Meeting-audio transcription" section before assuming every AI-adjacent capability lives under `backend/app/ai/`.

Common commands:
- `docker compose up -d postgres && docker compose run --rm api python scripts/init_db.py` — create schema
- `docker compose run --rm api python scripts/seed_sources.py && docker compose run --rm api python scripts/seed_prompts.py` — seed source registry + versioned prompts (both idempotent)
- `docker compose up -d api worker` — dashboard at `http://localhost:8010`, API docs at `/docs`
- `backend/tests/` (pytest, ~99% coverage as of 2026-07-08): `docker compose run --rm api pytest`. Runs against a real `civic_radar_test` Postgres database (not sqlite — several models need pgvector/JSONB), each test isolated in a rolled-back transaction (see `join_transaction_mode="create_savepoint"` in `tests/conftest.py` — required since app code calls `db.commit()` for real; `db_session_factory` exposes the same sessionmaker directly for code like `worker.py` that opens its own `SessionLocal()` rather than taking a `db` param). Effectively full coverage: ingestion (all connectors/fetchers including `ingestion/pipeline.py`'s meeting-linking helpers, which were a real 0% gap since the earlier tests only used the `generic` connector), alerting/scoring/heuristics, the full REST router layer, issue matching, OCR/parsing (mocked `pdfplumber` — the thing worth protecting is our OCR-cap/`page.close()` logic, not pdfplumber itself), the full AI orchestration layer (note `OLLAMA_BASE_URL` resolves to a genuinely reachable `madhatter.local` in this environment, so every Ollama-touching test explicitly monkeypatches rather than assuming unavailability), the worker loop, and the dashboard/digest/markdown-export/db/http-client layers. The 6 remaining uncovered lines are all genuinely unreachable (FK-constrained dead code, or `worker.py`'s `if __name__ == "__main__"` guard). Two real inconsistencies surfaced while writing these tests were fixed: `GET /api/crime-incidents/{id}` now raises a real 404 instead of 200ing with an error body, and `ManualSubmissionOut` now includes `operator_note`.

Follow the existing stack and module layout in `backend/app/` rather than introducing a different framework or reorganizing — it mirrors the PRD's architecture directly (see below).

## What This Project Is

Ventura Civic Radar is a local-first civic intelligence system that monitors official Ventura County / City of Ventura government sources (agendas, staff reports, public notices, campaign filings) and turns them into tracked, source-linked "issues" with timelines, deadlines, and reviewable AI summaries. Full detail lives in `prd.md` — read it before implementing any feature; the summary below only covers what recurs across the design and would otherwise require reading the whole document to piece together.

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
