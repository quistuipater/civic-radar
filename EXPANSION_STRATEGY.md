# Multi-Jurisdiction Expansion Strategy

Notes from a 2026-07-10 planning discussion about whether/how to expand Civic
Radar beyond Ventura. Not a commitment to build any of this — a record of the
reasoning so it doesn't need re-deriving. See `../santa_cruz_civic_radar/` for
the first fork built under this thinking, and that repo's README for the
concrete per-source findings from forking it.

## Deployment unit: city, not county

Both existing repos (Ventura, Santa Cruz) are structured as "one city's
connectors + a handful of county-only sources" in a single repo — but that
was incidental, not a deliberate county-level design. The more accurate
model, worked out in this discussion:

- **City is the real franchise unit.** The expensive part of onboarding a
  new jurisdiction is platform discovery + connector-building (does this
  city use CivicPlus, PrimeGov, Granicus, OnBase, a legacy ASP system,
  something else?) — that cost is per-city and doesn't shrink or grow with
  the county around it.
- **County is a small, mostly-fixed add-on** — Board of Supervisors, county
  Planning Commission, Sheriff crime data (if it exists), county Elections —
  typically 4-6 sources, regardless of how many cities within the county are
  also instrumented.
- Total cost therefore scales with **number of incorporated cities
  instrumented within a county**, not population directly. Correlated with
  population at a regional level (bigger metros → more incorporated cities)
  but not a clean multiplier: LA County has ~88 incorporated cities, San
  Bernardino County is comparably huge in population but has ~24, and San
  Francisco is a consolidated city-county (one government, not two).
- **Real wrinkle, not just theory**: the city/county boundary isn't even
  clean for a single source category. Santa Cruz *city* runs its own
  separate NetFile campaign-finance feed (`CRUZ`) distinct from the
  *county's* (`SCCO`) — so "campaign finance is always county-level" is
  false. Every source needs the same per-jurisdiction verification done for
  Santa Cruz's fork, not an architecture-level assumption.

## Campaign finance: don't build a shared/routing system yet

Considered pulling campaign-finance ingestion out into a shared per-county
service whose output gets filtered and routed into whichever city instance
each filing belongs to (avoids re-fetching/re-archiving the same county-wide
NetFile feed once per city instrumented in that county).

**Decision: not yet.** Reasons:
- No actual duplication exists today — Ventura and Santa Cruz are different
  counties, so nothing is being double-fetched. The problem only becomes
  real once a second city *within an already-covered county* gets
  instrumented.
- Real sample data undercuts the "filter by city" premise anyway: the three
  live filings pulled from Santa Cruz's feed during this discussion were a
  teachers'-union PAC, a water-district director race, and a county
  supervisor race — zero were city-council candidates. If that's
  representative, most of what's in a county's feed doesn't cleanly
  attribute to any single city, which argues for treating campaign finance
  as inherently county-scoped content surfaced at a future county-aggregate
  layer, not pushed down into per-city databases.
- Matches the standing project bias against premature abstraction (same
  reasoning as the "No n8n" decision) — build the shared ingester + routing
  only when a real second-city-same-county case shows up.

## Which CA counties are worth building for

California has 58 counties. Rough population/infrastructure cut:
~9 over 1M (clearly worth it), ~20-25 more in the 100K-1M range (real
signal — meeting volume, land-use activity, filings), ~25 under 100K with
thin signal and often no real digital infrastructure. So **~30 of 58** clear
a reasonable bar by population alone.

**Population doesn't predict digital-infrastructure quality, though** — the
gating factor for "worth it" is whether the jurisdiction has actually
digitized its meeting/filing systems, which population doesn't tell you.
Santa Cruz County (pop. ~270K, tech-adjacent identity) still turned out to
have a legacy classic-ASP frameset system for its Planning Commission,
found only by doing the same ~15-20-minute per-jurisdiction platform check
used throughout the Santa Cruz fork (agenda system, campaign-finance host,
ArcGIS crime-data presence, Granicus meeting-audio availability with real
populated items). That reconnaissance pass, not population rank, is the
actual next step before picking the next city/county to fork for.

Effort split if pursuing this: **discovery is fast** (~15-20 min per
jurisdiction to identify platforms and rule out bot walls — the same pass
just run on Santa Cruz), but **wiring sources in is the bottleneck**.
Of the ~6 source categories checked for Santa Cruz, only 2 (PrimeGov,
NetFile) reused platforms already supported by existing connectors; the
rest needed real new work (OnBase Agenda Online's two-step JS download
flow, the county Planning Commission's legacy ASP search tool, Granicus
HLS/CloudFront-token media instead of a populated podcast RSS feed).
Jurisdictions that cluster on already-supported platforms are near-zero-cost
to add; jurisdictions needing novel platforms are real connector-building
work that should be weighed against that cost, not just against population
size.

## Cloud deployment cost (if swapping local Ollama/WhisperX for hosted APIs)

Explored whether the whole stack could become genuinely cloud-portable (no
GPU/madhatter dependency) by swapping the AI layer's default from local
Ollama + WhisperX to Anthropic's Claude API + ElevenLabs Scribe (STT with
diarization included, up to 32 speakers) + Voyage AI (embeddings — Anthropic
doesn't offer an embeddings endpoint itself).

**This would reverse a stated project principle** (CLAUDE.md: "core product
must not depend on cloud inference... never a default dependency") — worth
flagging explicitly if ever pursued, not something to do as a side effect of
wanting easier deployment.

Cost estimate, grounded in Ventura's actual real-world volume (not a
guess): ~25 new documents/week, ~250 AI calls/month across
classification/summarization/agenda-item-extraction/meeting-results, and
~15-20 meeting recordings/month averaging ~1.75 hours:

| Component | Volume/month | Cost/month |
|---|---|---|
| Claude (Sonnet 5, all 4 task types) | ~1M input / ~100K output tokens | ~$4.50 |
| ElevenLabs Scribe (transcription+diarization) | ~26 hours of audio | ~$5.70 |
| Voyage AI embeddings | ~150K tokens | ~$0 (within free tier) |
| **Total per city+county instance** | | **~$10-15/month** |

Inference cost is a rounding error next to any hosting bill — running this
for 20-30 counties would run roughly $200-450/month in AI inference total.
The real unlock isn't the dollar figure, it's that both swaps eliminate the
GPU/madhatter dependency entirely, which is what's actually blocking
cloud-only deployment today. Caveat: this assumes typical document sizes:
a handful of documents in this project have been genuinely enormous (the
6,102-page packet that motivated the OCR-cap/parse-timeout logic) — even
there the per-call cost stays small (100K input tokens on Sonnet 5 is
~$0.30), so it's not a scary tail risk, just a reason to keep the existing
chunking/caps rather than assume every document is small.
