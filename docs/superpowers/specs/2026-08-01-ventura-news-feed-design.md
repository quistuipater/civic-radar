# Ventura County News Feed — Design

## Purpose

Add a standalone retrieval engine that monitors Ventura County local news
outlets, archives their articles, classifies each one against the existing
civic-topic ontology (`TOPIC_TAXONOMY` in `core/app/ai/prompts.py`), and
surfaces the result as a browsable, filterable "News" tab on the Ventura
dashboard. This closes a real gap: today the only signal in Civic Radar is
primary government records (agendas, staff reports, notices); local press
coverage of the same jurisdictions is invisible to the tool.

## Non-goals

- **No integration with Issues/scoring.** News articles are context, not a
  reviewable civic record — they do not become `Document` rows, do not flow
  through `classify_document`/`AiOutput`, and are not cross-linked to
  existing Issues. This was an explicit choice: keep the news pipeline
  genuinely decoupled from the government-document pipeline rather than
  bolting news onto tables shaped for agenda items (APNs, ordinance numbers,
  meeting dates — none of which apply to a news article).
- **No paywall or bot-block circumvention.** Every outlet included here is
  reachable through a feed the outlet (or Google News, for VC Star) makes
  freely and publicly available. No full-text fetch is ever attempted
  against a source that didn't offer it freely, and no archive-mirror
  workarounds (e.g. archive.today) are used.
- **No auto-update polling on the News tab.** Unlike the Logs tab, news
  doesn't need a live-tail view — a cursor-based "Load more" is enough.
- **Ventura-only data**, though the code lives in shared `core/` so Santa
  Cruz/Boston can adopt it later with their own outlet lists — same pattern
  as every other shared connector.

## Outlet list

Seeded in `cities/ventura/seed_news_sources.py`, following the "verified
live" convention of `seed_sources.py`. Two connector types:

| Outlet | Feed | Connector |
|---|---|---|
| Ventura Breeze | `https://venturabreeze.com/feed/` | `wordpress_rss` |
| The Camarillo Acorn | `https://www.thecamarilloacorn.com/feed/` | `wordpress_rss` |
| The Acorn (portal — Agoura Hills/Calabasas/Oak Park/Westlake) | `https://www.theacorn.com/feed/` | `wordpress_rss` |
| Simi Valley Acorn | `https://www.simivalleyacorn.com/feed/` | `wordpress_rss` (verify live at seed time) |
| Moorpark Acorn | `https://www.mpacorn.com/feed/` | `wordpress_rss` (verify live at seed time) |
| Thousand Oaks Acorn | `https://www.toacorn.com/feed/` | `wordpress_rss` (verify live at seed time) |
| Ojai Valley News | `https://www.ojaivalleynews.com/feed/` (unconfirmed — 404'd once, rate-limited on retry) | `wordpress_rss` (verify live at seed time; drop if no working feed found) |
| Ventura County Star | `https://news.google.com/rss/search?q=site%3Avcstar.com&hl=en-US&gl=US&ceid=US%3Aen` | `google_news_proxy` |

Fillmore Gazette and Santa Paula Times were identified as existing
publications but no live feed was verified during design; add them at seed
time if a working feed is found, otherwise leave out rather than guess a
URL.

`NewsSource.connector` distinguishes the two feed shapes:
- `wordpress_rss`: standard WordPress RSS 2.0, `<link>` points directly at
  the outlet's own article page. Eligible for best-effort full-text fetch.
- `google_news_proxy`: Google's own search-RSS, `<link>` points at a
  `news.google.com` redirect, not the publisher's page. **Never** fetch
  through the link — classify from `<title>`/`<description>` only. This is
  the only VC Star pathway; VC Star's own RSS is defunct (official feed
  directory is from 2014; Gannett has since disabled native RSS on most of
  its properties).

## Data model

New tables in `core/app/models.py`, independent of `Source`/`Fetch`/`Document`:

```python
class NewsSource(Base):
    __tablename__ = "news_sources"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(Text, nullable=False)
    outlet_url: Mapped[str] = mapped_column(Text, nullable=False)
    rss_feed_url: Mapped[str] = mapped_column(Text, nullable=False)
    connector: Mapped[str] = mapped_column(Text, nullable=False)  # "wordpress_rss" | "google_news_proxy"
    polling_interval_minutes: Mapped[int] = mapped_column(Integer, default=60)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    articles: Mapped[list["NewsArticle"]] = relationship(back_populates="news_source")


class NewsArticle(Base):
    __tablename__ = "news_articles"

    id: Mapped[uuid.UUID] = uuid_pk()
    news_source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("news_sources.id"))
    title: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False, unique=True)  # dedup key
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    summary: Mapped[str | None] = mapped_column(Text)      # RSS <description>
    full_text: Mapped[str | None] = mapped_column(Text)    # best-effort scraped body; always null for google_news_proxy
    archive_path: Mapped[str | None] = mapped_column(Text)
    topic_categories: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    classification_method: Mapped[str] = mapped_column(Text, nullable=False)  # "heuristic" | "ai"
    classification_confidence: Mapped[str] = mapped_column(Text, nullable=False)  # "low" | "medium" | "high"

    news_source: Mapped["NewsSource"] = relationship(back_populates="articles")
```

No migration framework in this codebase (confirmed in the Logs-tab design) —
`scripts/init_db.py`'s `Base.metadata.create_all(bind=engine)` picks up both
new tables on its next run, same as `AppLog` was added.

## Retrieval flow

New package `core/app/news/` (not `ingestion/` — visibly separate from the
government-document pipeline):

- `news/feed_parser.py`: parses RSS/Atom XML into `(title, link, summary,
  published_at)` tuples, using the same `xml.etree.ElementTree` approach as
  `ingestion/connectors/netfile_rss.py`. Handles both feed shapes
  (`wordpress_rss` output is standard RSS 2.0; `google_news_proxy` output is
  also RSS 2.0, so one parser covers both — the connector distinction only
  matters for what happens *after* parsing).
- `news/retrieval.py`: `poll_news_source(db, news_source) -> int` (returns
  count of new articles):
  1. Fetch `rss_feed_url` (reuse `ingestion.http_client.fetch_url`).
  2. Parse items via `feed_parser`.
  3. For each item whose `url` doesn't already exist in `news_articles`:
     archive-and-classify (below). Existing `url`s are skipped — this is the
     dedup mechanism (a feed re-serving the same item on the next poll is a
     no-op, not a duplicate row).
  4. Update `NewsSource.last_fetched_at`/`last_error`/`consecutive_failures`,
     same bookkeeping shape as `ingest_source` in `ingestion/pipeline.py`.
- For each new item:
  - If `connector == "wordpress_rss"`: best-effort GET the article page.
    On success, archive the raw HTML via `archive.write_archive_file` (new
    subdirectory, e.g. `archive/news/<outlet-slug>/...`) and extract body
    text via the existing `parsing/extract.py`'s HTML-parsing path (same
    "first-pass heuristic" extraction already used for gov HTML — no new
    dependency). On fetch/extract failure, fall back to the RSS `summary`
    alone; the article is still saved, just with `full_text = None`.
  - If `connector == "google_news_proxy"`: never fetch through the link.
    `full_text` stays `None` unconditionally; classification runs on
    `title` + `summary` only.
  - Classify (below), then insert the `NewsArticle` row.

## Classification

`core/app/news/classify.py`, structured like `ai/classify.py` but standalone
(no `Document`/`AiOutput` dependency):

- **Heuristic pass** (`heuristic_classify_article`): keyword/phrase matching
  against `TOPIC_TAXONOMY` (imported from `ai/prompts.py` — one ontology
  shared with the gov-document classifier, not a forked copy) over
  `title + " " + summary + " " + (full_text or "")`. Every one of the 25
  taxonomy categories must have an explicit keyword/phrase list defined in
  the implementation plan (not a partial example set) — two illustrative
  entries: `zoning` → "rezon", "zoning", "variance"; `police_public_safety`
  → "police", "sheriff", "arrest", "crime". Score by hit count per category;
  assign the top 1-3 categories whose score clears a threshold (define the
  exact threshold value in the plan, e.g. "≥1 keyword hit"). If nothing
  clears the threshold, the heuristic pass yields no categories — that's
  the fallback trigger.
- **AI fallback**: only invoked when the heuristic pass finds nothing.
  Reuses `ai/ollama_client.generate_json`, with a new news-specific prompt
  in `ai/prompts.py` (`NEWS_CLASSIFICATION_PROMPT` — same taxonomy, adapted
  framing: "classify this news article", not "classify this agenda item").
- **Confidence values** (fixed rule, not a judgment call per-article):
  heuristic match → `classification_confidence = "medium"` (keyword
  counting, not model judgment). Successful AI fallback →
  `classification_confidence = "high"`. Heuristic empty AND AI
  unavailable/erroring/still-empty → `topic_categories = []`,
  `classification_method = "heuristic"`, `classification_confidence =
  "low"` — this path never blocks ingestion; the article is still saved.
- `classification_method` records which path actually produced the result,
  making heuristic accuracy auditable later (e.g. "how often does AI
  fallback fire") without a separate eval harness now.

## API

New `core/app/routers/news.py`, mounted at `/api/news`, following the same
router convention as `routers/logs.py`.

New schema in `schemas.py`:

```python
class NewsArticleOut(BaseModel):
    id: str
    title: str
    url: str
    outlet_name: str
    published_at: datetime | None
    summary: str | None
    topic_categories: list[str]
    classification_method: str
    classification_confidence: str
```

`GET /api/news` query params: `topic` (category | `all`, default `all`),
`source_id` (`NewsSource.id` | `all`, default `all`), `before` (a plain ISO
datetime string — same cursor shape `/api/logs` actually implements, not a
composite pair, for "Load more"), `limit` (default 50). No `after` param —
no polling, so no need for a "newer than" cursor. Malformed
`before`/`source_id` → `400`, same pattern established in the Logs-tab fix
round (never let a bad param produce an uncaught 500).

## Page & UI

`core/app/dashboard.py`: new `GET /news` route renders a template shell
(filter bar + empty list) and passes `NewsSource` rows for the outlet
dropdown — same shape as `logs_page`.

`core/app/templates/news.html` (extends `base.html`):
- Filter bar: **Topic** select (All + each `TOPIC_TAXONOMY` category),
  **Outlet** select (All + each `NewsSource.name`)
- List: headline (linked to the original article `url`), outlet name,
  published date, topic badges (reuse `.badge` CSS from `base.html`),
  expandable `<details>` for the summary
- "Load more" button using the `before` cursor — no auto-update interval,
  per the non-goal above
- Changing a filter clears the list and re-fetches from the start (cursor
  reset), same behavior as the Logs tab's filter handling
- `<a href="/news">News</a>` added to `base.html`'s nav, after `/logs` —
  shared `core/`, so it appears on all three cities' dashboards, but only
  Ventura has `NewsSource` rows seeded, so Santa Cruz/Boston see an empty
  tab until/unless they get their own outlet list.

## Worker integration

`worker.py` gains `run_news_batch(db)`, called from the existing `tick()`
loop. For each enabled `NewsSource` whose `polling_interval_minutes` has
elapsed since `last_fetched_at` (same throttle shape as the existing
`run_ingestion_tick` per-`Source` throttling), call
`news.retrieval.poll_news_source(db, news_source)`.

Crash-site errors (`logger.exception`) inside this step are **not** tagged
with `extra={"source_id": ...}` — `AppLog.source_id` is a foreign key to
`sources.id`, and widening it to also accept `news_sources.id` would
compromise the Logs tab's decoupling from this feature. Untagged errors
(`source_id = None`) already show under "general" in the Logs tab's source
filter, which is sufficient: a worker crash during news polling is still
fully visible, just not filterable by which news outlet caused it.

## Testing scope

- `feed_parser`: valid RSS parses correctly for both feed shapes; malformed
  XML returns an empty list rather than raising
- `poll_news_source`: dedup by `url` (existing URL is skipped, not
  re-inserted); `wordpress_rss` full-text fetch failure falls back to
  `summary`; `google_news_proxy` never attempts a full-text fetch even if
  given a plausible-looking `url`
- `heuristic_classify_article`: keyword scoring assigns expected categories
  above threshold; empty result when nothing matches (triggers AI fallback
  path)
- AI fallback: invoked only when heuristic yields nothing; Ollama failure
  degrades to `topic_categories = []` without raising
- `/api/news`: topic filter, source filter, `before` cursor pagination,
  malformed-param → 400 (not 500)
- Worker: `run_news_batch` throttles per-`NewsSource` polling interval,
  same shape as existing `run_ingestion_tick` tests

## Rollout

Shared `core/` change — implementing once makes the tables, connector code,
and UI available to all three cities, but only Ventura gets seeded
`NewsSource` rows via `cities/ventura/seed_news_sources.py`. Each city's
`docker-compose.yml` needs no changes; new tables are created by the
standard `init_db.py` path already used per-city (must be re-run against
Ventura's live database as part of rollout, same as the Logs-tab rollout).
