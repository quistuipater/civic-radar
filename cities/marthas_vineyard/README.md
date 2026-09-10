# Martha's Vineyard Civic Radar

A fork of [Civic Radar](../../README.md) for Martha's Vineyard, MA (the six
towns of Dukes County: Aquinnah, Chilmark, Edgartown, Oak Bluffs, Tisbury,
West Tisbury). See [`CLAUDE.md`](CLAUDE.md) for the full architecture
summary and [`../../OVERVIEW.md`](../../OVERVIEW.md) for the platform-wide
design.

## Quick start

```bash
cd cities/marthas_vineyard
cp .env.example .env
docker compose up -d postgres
docker compose run --rm api python scripts/init_db.py
docker compose run --rm api python scripts/seed_sources.py
docker compose run --rm api python scripts/seed_prompts.py
docker compose up -d api worker
```

Dashboard: `http://localhost:8014`, API docs at `/docs`.

## What's implemented (Phase 0, as of 2026-09-10)

Reconnaissance covered all six towns, Dukes County, and the Martha's
Vineyard Commission before any source was seeded. Two towns cleanly matched
an existing connector; everything else is a confirmed, documented gap, not
an unstarted one.

| Source | Status | Notes |
|---|---|---|
| Town of Oak Bluffs (AgendaCenter) | **Live** | Real CivicPlus AgendaCenter, 816 document links at fetch time. Zero new code. |
| Town of Tisbury (AgendaCenter) | **Live** | Real CivicPlus AgendaCenter, 524 document links, 17 board/committee categories. Zero new code. |
| MA OCPF (state/county races covering MV) | **Live** | Senate (Cape & Islands), House (Barnstable/Dukes/Nantucket), Dukes County Sheriff, Cape & Islands DA. Reuses Boston's `ocpf.py` connector (now generalized to a per-source allowlist). No MV town has its own OCPF-registered local candidate — Select Board seats etc. file locally with the town clerk, not OCPF. |
| Edgartown | **Gap — bot-walled** | HTTP 403 from an edge bot-wall (Akamai/Cloudflare), confirmed with a real browser UA. Same class of gap as Ventura's Elections/AWS-WAF wall; not bypassed, per project policy. |
| Chilmark | **Gap — bot-walled** | Same as Edgartown. |
| Aquinnah | **Gap — bot-walled** | Same as Edgartown. |
| West Tisbury | **Gap — new platform needed** | Runs a bespoke legacy PHP calendar (`agenda_and_minutes/index.php?view=month&...`), not CivicPlus. Real connector work, not config. |
| Dukes County (dukescounty.gov) | **Gap — new platform needed** | Runs "EvoGov" (not seen in any prior fork). `/meetings` is reachable but unparsed. |
| Martha's Vineyard Commission (mvcommission.org) | **Gap — bot-walled** | Arguably the most consequential body here — it's the island's actual land-use/development review authority, unique to MV. Akamai-bot-walled like the three towns above. |
| Meeting audio, crime data, building permits, food inspections | **Not investigated** | Unlike the gaps above, these haven't been checked at all yet — MV's towns may simply be too small for public structured-data feeds of the kind Ventura/Boston have, but that's a guess, not a finding. |

See `seed_sources.py`'s module docstring for the full per-source write-up
(exact URLs, verification dates, HTTP evidence).

## Known limitations

- MA OCPF's `/reports/log` returns only the ~50 most recent filings
  statewide with no pagination or date-range params — if MV-relevant
  filings are ever outpaced by other MA filings between polls, some could
  be missed. Same caveat as Boston's OCPF source.
- No meeting-audio, crime-data, building-permit, or food-inspection sources
  are configured (`city_settings.py` doesn't exist for this fork — the
  built-in empty defaults in `app/city_config.py` are correct until one of
  those is confirmed to exist).
