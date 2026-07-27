# Civic Radar — Platform Overview

*This repository (`santa_cruz_civic_radar`) is the Santa Cruz instantiation of
the Civic Radar platform. This document describes the platform as a whole —
what all three instantiations share and how they differ — not just this one
deployment.*

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

## One platform, three instantiations

Civic Radar is one codebase — schema, pipeline, dashboard, AI guardrails —
deployed three times against three different jurisdictions. Each
instantiation is a fork that reuses the shared engine as-is and adds only
what that jurisdiction's real government platforms require:

| | **Ventura** *(origin)* | **Santa Cruz** *(this repo)* | **Boston** |
|---|---|---|---|
| Jurisdiction | City of Ventura + Ventura County | City of Santa Cruz + Santa Cruz County | City of Boston + Massachusetts state (OCPF) |
| Dashboard port | 8010 | 8012 | 8013 |
| City agendas platform | CivicPlus AgendaCenter (generic connector) | Hyland OnBase — bespoke, session-stateful connector (`onbase_agenda.py`) | Legistar REST/OData API — bespoke connector (`legistar.py`) |
| County/board agendas | PrimeGov (BOS + Planning Commission share one platform) | PrimeGov for BOS; a legacy classic-ASP search tool for Planning Commission — bespoke connector (`scc_planning_search.py`) | Zoning Board of Appeal via the same Legistar module as City Council (different `BodyId`) — pure config |
| Campaign finance | NetFile (generic connector) | NetFile, county (`SCCO`) + city (`CRUZ`) — 4 feeds | Massachusetts OCPF — bespoke connector (`ocpf.py`), JSON API |
| Crime data | *(not implemented)* | Investigated, not found — city/county only publish jurisdiction-boundary layers, no incidents | Boston PD via ArcGIS — pure `AGENCY_CONFIG` addition, no new code |
| Elections/notices | NetFile-adjacent; bot-walled (AWS WAF) | County Elections Division (generic connector, no bot wall here) | Bespoke connector (`boston_public_notices.py`) — each notice is its own HTML page, not a linked PDF |
| Meeting audio | Working (Granicus podcast feed populated) | Not usable — county's podcast feed returns zero items, both video streams CloudFront-gated | Not usable — podcast feed *is* populated, but audio files are CloudFront-gated (403 even with matching Referer) |

The pattern across all three: **most connectors turn out to be reusable
as-is** (PrimeGov, NetFile, the generic HTML/RSS harvester) because civic
software vendors serve multiple jurisdictions. The exceptions are real
engineering, not configuration — a jurisdiction's genuinely different
platform (OnBase instead of CivicPlus, Legistar instead of PrimeGov, OCPF
instead of a county filing officer) requires a new bespoke, session-stateful
ingestion module rather than a config tweak. Each fork's `README.md` and
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

`prd.md` (present in all three repos) is the platform's product requirements
document — architecture, schema, pipeline shape, and phase structure are
jurisdiction-agnostic and apply to all three as written. It was originally
authored for Ventura, so anything in it naming Ventura's specific agencies or
geography is a stale artifact of where the platform started, not a
requirement — each fork should re-scope those specifics for its own
jurisdiction rather than treat them as gospel.

## How it's implemented

Every instantiation runs the same single Docker Compose stack:

- **postgres** (pgvector image) — the entire schema: sources, fetches,
  documents + chunked/embedded text, meetings, agenda items, issues, issue
  events, alerts, and versioned AI outputs.
- **ollama** — local model serving for classification, summarization, and
  embeddings.
- **api** — a FastAPI app that is *also* the dashboard: a server-rendered
  Jinja2 UI (no separate frontend build) plus the REST API, in one process.
- **worker** — a Python scheduler loop that stands in for the
  originally-planned n8n orchestration layer; it polls each source on its
  configured interval and pushes documents through the pipeline.

Pipeline shape, source to dashboard — identical across instantiations:

```
official source → fetch → raw archive (hash + store)
  → parse (PDF/HTML text, page/section structure)
  → structured extraction (dates, project/ordinance numbers, deadlines)
  → embeddings + AI classification/summarization
  → issue matching (exact-identifier auto-link, or fuzzy semantic
    suggestion requiring human confirmation)
  → alert scoring (levels 1-4)
  → review queue → dashboard
```

Port numbers (8010/8012/8013 for dashboard, similarly offset Postgres/Ollama
ports in each `docker-compose.yml`) are deliberately staggered so all three
stacks can run simultaneously on the same host (`madhatter`) without
colliding.

## How to use it

These commands are the same in any of the three repos — run from within
this one, they stand up the Santa Cruz instantiation specifically:

```bash
cp .env.example .env
docker compose up -d postgres
docker compose run --rm api python scripts/init_db.py
docker compose run --rm api python scripts/seed_sources.py
docker compose run --rm api python scripts/seed_prompts.py
docker compose up -d api worker
```

Dashboard: `http://localhost:8012` (Ventura: 8010, Boston: 8013) — API docs
at `/docs`.

**In the dashboard:**

- **Home** — recent activity across all sources.
- **Daily Digest** — top changes, upcoming hearings/votes, new notices,
  items needing review, approaching deadlines, in one page (also available
  as Markdown at `/api/digest/daily.md`).
- **Review Queue** — high-priority alerts awaiting approve/reject, documents
  that failed parsing, sources with repeated fetch failures, and unverified
  social/manual submissions.
- **Sources** — the registry of monitored feeds and their fetch health.
- **Issues** — the tracked civic matters; create one manually, watch
  documents get suggested or auto-linked to it, and export a Markdown brief
  once it's substantial.
- **Submit Manual Item** — for anything worth tracking that isn't from an
  official source (a Nextdoor post, a tip) — stored as unverified until
  corroborated.

Any document's detail page shows its original URL, its local archive path
(a clickable link to the actual archived file), parser status, extracted
identifiers, AI outputs (or a button to run classification on demand), and
linked/suggested issues.

**Local AI (recommended):**

```bash
docker compose up -d ollama
docker compose exec ollama ollama pull llama3.1:8b
docker compose exec ollama ollama pull nomic-embed-text
```

Without Ollama running, classification still works via a deterministic
heuristic fallback — everything it produces is marked low-confidence and
routed to the review queue rather than trusted outright. Since all three
instantiations can share one Ollama instance on `madhatter`, consider
pointing them at the same one rather than running three separately and
tripling multi-GB model downloads.

**Tests:** `docker compose run --rm api pytest` — runs against a real
Postgres test database (several models need pgvector/JSONB, not
sqlite-compatible), each test isolated in a rolled-back transaction.

**Remote access:** the dashboard has no authentication and is meant to stay
LAN-only for now. To let someone outside the LAN use it, put it behind a
mesh VPN (e.g. Tailscale) scoped with an ACL grant to just the host and port
it runs on, rather than exposing it to the public internet.

See this repo's `README.md` for the full Santa-Cruz-specific command
reference, including manually ingesting a document from a source that turns
out to be bot-walled.

## Next steps

**Per-instantiation gaps:**

- **Santa Cruz** — crime data unavailable (no incident-level feed from
  either agency); meeting audio unusable (empty podcast feed, gated video).
  Phase 1 source list for Santa Cruz (which city boards/commissions, which
  county bodies beyond BOS/Planning) still needs deliberate scoping — see
  this repo's README "TODO: Santa Cruz source research."
- **Boston** — meeting audio unusable (podcast feed *is* populated, unlike
  Santa Cruz, but the files themselves are CloudFront-gated).
- **Ventura** — Elections sits behind an active AWS WAF bot challenge; only
  a page snapshot gets archived there today rather than real filings.

**Platform-level:**

- **Extract genuinely shared code into a real shared package**, rather than
  three independently-forked copies of the same engine. Right now a bug fix
  or schema change made in one instantiation has to be manually ported to
  the other two (this happened with the branding/genericization pass and
  the review-queue column merge, both applied per-repo). A shared core
  library with jurisdiction-specific connectors/config as the only
  per-instantiation code would remove that duplication risk.
- **Standardize what "pure config" vs. "new connector" means** as a
  documented decision framework, now that three forks have each made this
  call independently — would make onboarding a fourth jurisdiction faster
  and more consistent.
- **Authentication**, if/when any instantiation moves beyond
  single-operator, LAN/VPN-only use — currently none exists anywhere, by
  design (Phase 1 scope for all three).
- **Re-scope `prd.md`** per jurisdiction, or maintain one platform-level PRD
  with jurisdiction-specific appendices, instead of each fork inheriting
  Ventura's copy verbatim with a "stale but architecturally valid" caveat at
  the top.
- Phase 2 (additional cities, school boards, water districts, LAFCo-style
  bodies) and Phase 3 (public-facing publishing/subscriptions) are
  explicitly out of scope for every instantiation until Phase 1 is solid
  there and someone decides to expand — see `prd.md` §6 and §23.
