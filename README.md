# Civic Radar

Local-first civic intelligence: watches official government sources
(agendas, staff reports, notices, campaign filings), archives them, and uses
local AI to turn them into tracked, reviewable "issues" with timelines and
deadlines. Full detail — purpose, design principles, architecture, and how
to run it — is in [`OVERVIEW.md`](OVERVIEW.md).

This repo is a monorepo: one shared engine (`core/`) plus three
per-jurisdiction instantiations (`cities/ventura/`, `cities/santa_cruz/`,
`cities/boston/`), each a self-contained Docker Compose project.

## Quick start

~~~bash
cd cities/santa_cruz   # or ventura, or boston
cp .env.example .env
docker compose up -d postgres
docker compose run --rm api python scripts/init_db.py
docker compose run --rm api python scripts/seed_sources.py
docker compose run --rm api python scripts/seed_prompts.py
docker compose up -d api worker
~~~

Dashboard: Ventura `http://localhost:8010`, Santa Cruz `:8012`, Boston
`:8013`.

## Layout

- `core/` — the engine: schema, pipeline, dashboard, REST API, AI layer,
  every ingestion connector (generic and bespoke). Shared by all three
  cities; see `OVERVIEW.md` for the full module map.
- `cities/<city>/` — that city's seed data, Docker Compose project, `.env`,
  and README/CLAUDE.md. See `cities/<city>/README.md` for what's actually
  specific to that deployment (real sources, known gaps).
- `docs/organization-tracker/` — requirements for the bounded module that
  converts archived evidence into time-aware organizational state and reviewed
  change events; Ventura is the MVP deployment.
- `whisperx_service/` — standalone meeting-audio transcription service.
- `prd.md` — the platform's product requirements document.
- `EXPANSION_STRATEGY.md` — the planning notes behind the "city is the
  franchise unit" model this repo's structure follows.
- `OVERVIEW.md` — start here for anything beyond a quick command reference.

See `OVERVIEW.md` for design principles, the full architecture, how per-city
branding/config flows through `core/` without forking it, and known gaps
per city.
