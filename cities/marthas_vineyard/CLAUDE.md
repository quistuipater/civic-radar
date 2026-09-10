# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Current State

**This is a fork of Ventura/Santa Cruz/Boston Civic Radar, bootstrapped for Martha's Vineyard, MA on 2026-09-10.** The engine (FastAPI + SQLAlchemy + Jinja2 dashboard + a Python worker as the ingestion scheduler), orchestrated via `docker-compose.yml` (postgres/pgvector, ollama, api, worker), is unchanged from the other forks' working Phase 0 build. **2 real sources are seeded and ingesting live**: Town of Oak Bluffs and Town of Tisbury, both real CivicPlus AgendaCenter sites (same connector as Ventura's City Council source, zero new code — confirmed live 2026-09-10, 816 and 524 document links respectively at fetch time), plus Massachusetts OCPF campaign-finance filings for the state/county races covering MV (Senate Cape & Islands, House Barnstable/Dukes/Nantucket, Dukes County Sheriff, Cape & Islands DA — reuses Boston's `ocpf.py` connector, now generalized to a per-source allowlist keyed by `Source.body` since two forks share it, see `core/app/ingestion/connectors/ocpf.py`'s docstring).

**Four real gaps were found and confirmed during reconnaissance, not left unstarted through neglect** — see `seed_sources.py`'s module docstring for the full writeup:
- **Edgartown, Chilmark, Aquinnah** — all three return HTTP 403 from an edge bot-wall (Akamai/Cloudflare, confirmed with a real browser UA, not a missing-page 404). Same class of gap as Ventura's Elections/AWS-WAF wall — this project's standing policy is not to bypass access controls, so these stay documented gaps rather than being worked around.
- **West Tisbury** — runs a bespoke legacy PHP calendar (`agenda_and_minutes/index.php?view=month&...`), not CivicPlus. Needs real new connector code, not a config change.
- **Dukes County** (dukescounty.gov) — runs "EvoGov", a platform not seen in any prior fork. Has a reachable `/meetings` listing but it's unparsed; needs new connector code.
- **Martha's Vineyard Commission** (mvcommission.org) — arguably the single most consequential body in this jurisdiction for this project's purpose (it's the island's actual land-use/development review authority, a regional body unique to MV with no equivalent in any prior fork), and it's Akamai-bot-walled the same way the three towns above are.

Not yet investigated at all (unlike the confirmed gaps above): meeting audio, crime data, building permits, food inspections. MV's towns are small enough that public ArcGIS/CKAN structured-data feeds of the kind Ventura/Boston have may simply not exist — that's a guess, not a finding; verify before assuming either way.

Common commands:
- `docker compose up -d postgres && docker compose run --rm api python scripts/init_db.py` — create schema
- `docker compose run --rm api python scripts/seed_sources.py && docker compose run --rm api python scripts/seed_prompts.py` — seed source registry (3 real sources) + versioned prompts (both idempotent)
- `docker compose up -d api worker` — dashboard at `http://localhost:18014` (8014 was taken by an unrelated civic-radar-monitor service on the shared host, same class of escape as Boston's 18013), API docs at `/docs`
- `backend/tests/`: `docker compose run --rm api pytest`. No bespoke connector code exists in this fork yet (both live sources reuse connectors already covered by `core/tests/`), so there's no `cities/marthas_vineyard/tests/*.py` beyond a placeholder README — add tests there if/when this fork gets its own connector (West Tisbury, Dukes County EvoGov). Runs against a real `civic_radar_test` Postgres database (not sqlite — several models need pgvector/JSONB), each test isolated in a rolled-back transaction (see `join_transaction_mode="create_savepoint"` in `tests/conftest.py`).

Follow the existing stack and module layout in `backend/app/` rather than introducing a different framework or reorganizing — it mirrors the PRD's architecture directly (see below). Reconnaissance covered all six MV towns plus Dukes County plus the Martha's Vineyard Commission before writing any seed data — check `seed_sources.py`'s module docstring before assuming a gap here is unresearched; most of them are confirmed, not just missing.

## What This Project Is

Martha's Vineyard Civic Radar is a local-first civic intelligence system that monitors official Martha's Vineyard / Dukes County government sources (agendas, staff reports, public notices, campaign filings) and turns them into tracked, source-linked "issues" with timelines, deadlines, and reviewable AI summaries. Full detail lives in `prd.md` — read it before implementing any feature; the summary below only covers what recurs across the design and would otherwise require reading the whole document to piece together. **Note**: `prd.md` was written for Ventura Civic Radar and inherited as-is into this fork — its architecture (schema, pipeline shape, AI guardrails, phase boundaries) is city-agnostic and still applies, but anything mentioning specific Ventura agencies/geography by name is stale and should be re-scoped for Martha's Vineyard before being treated as a real requirement. Martha's Vineyard's civic-government structure also differs meaningfully from every prior fork's: it's six small, separately-incorporated towns (not one city), Dukes County has no independent operational weight comparable to a CA county's Board of Supervisors, and the Martha's Vineyard Commission is a regional land-use authority with real regulatory power over island-wide development that has no equivalent anywhere else in this project — don't assume Ventura/Boston/Santa Cruz's category boundaries (e.g. "one Planning Commission source covers land use") translate directly.

### Core Product Principle

**Archive first. Interpret second. Publish third.** Raw source material (HTML, PDFs, metadata) must be durably archived before any parsing, classification, or summarization happens. The AI layer is an analytical assistant, not the system of record — nothing should overwrite or bypass the raw archive.

### Target Deployment

- Runs on `madhatter`, a local Debian server/workstation (Docker Compose, NVIDIA GPU, ~16GB VRAM, ~32GB RAM) — shared with the Ventura/Santa Cruz/Boston Civic Radar deployments on the same host; see `docker-compose.yml`'s port comments (5435/11437/18014) for the offsets used to avoid colliding with the other three stacks.
- Local-first: core product must not depend on cloud inference. Ollama is the default; Claude can be made the primary path via the "Remote inference" toggle on the dashboard (off by default), and always falls back to local Ollama on a Claude failure.
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

Phase 1 (current target) is scoped to the two towns actually instrumented (Oak Bluffs, Tisbury) plus MA OCPF filings for MV-area state/county races — the specific list of what expands next (the other four towns, Dukes County, the MV Commission) is an open, already-researched backlog documented in `seed_sources.py`'s module docstring, not a Phase 2/3 item in the Ventura sense. Do not expand source coverage beyond Martha's Vineyard/Dukes County (e.g. other Massachusetts jurisdictions) or build public-facing subscription/publishing features unless explicitly asked — see `prd.md` §6 and §23 for the phase definitions and exit criteria (written for Ventura; the phase *structure* still applies, the specific agency list doesn't).
