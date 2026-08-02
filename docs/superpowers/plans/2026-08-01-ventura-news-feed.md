# Ventura County News Feed Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a standalone retrieval engine that monitors Ventura County local news outlet RSS feeds, archives+classifies articles against the existing civic-topic ontology, and surfaces them in a new "News" dashboard tab.

**Architecture:** New `NewsSource`/`NewsArticle` tables, wholly independent of the `Source`/`Fetch`/`Document` gov-document pipeline. A new `core/app/news/` package (feed parsing, heuristic+AI classification, retrieval orchestration) mirrors the shape of `ingestion/` and `ai/classify.py` without depending on either. A new `run_news_batch()` step joins the worker's existing tick loop. A new `/api/news` endpoint and `/news` page follow the exact conventions established by the Logs tab (`routers/logs.py`, `templates/logs.html`).

**Tech Stack:** FastAPI, SQLAlchemy (Postgres), Jinja2, vanilla JS, httpx, BeautifulSoup (already a dependency — no new packages).

## Global Constraints

- No migration framework exists in this codebase. New tables are created by `scripts/init_db.py`'s `Base.metadata.create_all(bind=engine)`, which is safe/idempotent to re-run. This is a rollout step, not a task — do not run it against a live database as part of any task; that happens once, at the end, per the design doc's Rollout section.
- This feature is genuinely decoupled from the government-document pipeline (`Source`/`Fetch`/`Document`/`AiOutput`) — do not add foreign keys, joins, or shared tables between the two. `AppLog.source_id` stays scoped to `sources.id` only; news-pipeline errors are logged untagged (`source_id=None`), which already surfaces under "general" in the existing Logs tab.
- The topic ontology (`TOPIC_TAXONOMY` in `core/app/ai/prompts.py`) is shared, imported, never forked or redefined.
- `full_text` and `archive_path` on `NewsArticle` are **only ever populated for `connector == "wordpress_rss"`**. For `connector == "google_news_proxy"` they are always `None` — the RSS `<link>` for that connector is a Google redirect, not the real article URL, so no fetch is ever attempted through it.
- Confidence values are a fixed rule, not a per-article judgment call: heuristic match → `"medium"`; successful AI fallback → `"high"`; heuristic-empty-and-AI-unavailable-or-empty → `"low"` with `topic_categories = []`. Every task touching classification must preserve this exactly.
- Follow existing test conventions: Postgres-backed tests via the `db`/`client`/`archive_root` fixtures in `core/tests/conftest.py`; `monkeypatch.setattr(<module>, "fetch_url", ...)` for HTTP mocking (see `test_ingestion_pipeline.py`'s `fake_response` helper); `httpx.Response(status_code=200, content=b"...")` to construct fake responses.
- Run tests via `docker compose run --rm api pytest <path> -v` from `cities/ventura/` (the existing dev workflow — bind-mounted code, shared Postgres container, no rebuild needed).

---

### Task 1: Data model — `NewsSource` and `NewsArticle`

**Files:**
- Modify: `core/app/models.py` (append after `AppLog`, at end of file)
- Modify: `core/tests/conftest.py` (add `NewsSource`, `NewsArticle` to imports; add `make_news_source`, `make_news_article` factories)
- Test: `core/tests/test_news_models.py` (new)

**Interfaces:**
- Produces: `NewsSource` (fields: `id`, `name`, `outlet_url`, `rss_feed_url`, `connector`, `polling_interval_minutes`, `enabled`, `last_fetched_at`, `last_error`, `consecutive_failures`, `created_at`, `updated_at`, relationship `articles`). `NewsArticle` (fields: `id`, `news_source_id`, `title`, `url` (unique), `published_at`, `fetched_at`, `summary`, `full_text`, `archive_path`, `topic_categories` (`ARRAY(Text)`), `classification_method`, `classification_confidence`, relationship `news_source`).
- Consumes: nothing new — `uuid_pk()`, `Base`, and the SQLAlchemy imports (`ARRAY`, `Boolean`, `DateTime`, `ForeignKey`, `Integer`, `Text`, `func`, `Mapped`, `mapped_column`, `relationship`) already exist at the top of `models.py`; no new imports needed there.

- [ ] **Step 1: Add the two model classes**

Append to the end of `core/app/models.py`:

```python
class NewsSource(Base):
    """A monitored local news outlet's RSS feed. Wholly independent of
    Source/Fetch/Document -- news coverage is context, not a reviewable
    civic record, and this table intentionally carries none of the
    gov-document-specific fields (APN, ordinance number, meeting date, ...)
    that Source/Document have.
    """

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
    """A single retrieved+classified news article. `full_text`/`archive_path`
    are only ever populated when `news_source.connector == "wordpress_rss"`
    -- see core/app/news/retrieval.py.
    """

    __tablename__ = "news_articles"

    id: Mapped[uuid.UUID] = uuid_pk()
    news_source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("news_sources.id"))
    title: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    summary: Mapped[str | None] = mapped_column(Text)
    full_text: Mapped[str | None] = mapped_column(Text)
    archive_path: Mapped[str | None] = mapped_column(Text)
    topic_categories: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    classification_method: Mapped[str] = mapped_column(Text, nullable=False)  # "heuristic" | "ai"
    classification_confidence: Mapped[str] = mapped_column(Text, nullable=False)  # "low" | "medium" | "high"

    news_source: Mapped["NewsSource"] = relationship(back_populates="articles")
```

- [ ] **Step 2: Add test factories**

In `core/tests/conftest.py`, add `NewsArticle` and `NewsSource` to the `from app.models import (...)` block (alphabetical, matching existing style), then add these two factory functions near `make_source`/`make_document`:

```python
def make_news_source(db, **overrides) -> NewsSource:
    defaults = dict(
        name="Test News Outlet",
        outlet_url="https://example.invalid",
        rss_feed_url="https://example.invalid/feed/",
        connector="wordpress_rss",
        polling_interval_minutes=60,
    )
    defaults.update(overrides)
    news_source = NewsSource(**defaults)
    db.add(news_source)
    db.flush()
    return news_source


def make_news_article(db, news_source: NewsSource | None = None, **overrides) -> NewsArticle:
    if news_source is None:
        news_source = make_news_source(db)
    defaults = dict(
        news_source_id=news_source.id,
        title="Test Article",
        url=f"https://example.invalid/article-{uuid.uuid4().hex[:8]}",
        summary="A test article summary.",
        topic_categories=[],
        classification_method="heuristic",
        classification_confidence="low",
    )
    defaults.update(overrides)
    article = NewsArticle(**defaults)
    db.add(article)
    db.flush()
    return article
```

- [ ] **Step 3: Write the failing test**

Create `core/tests/test_news_models.py`:

```python
"""Tests for NewsSource/NewsArticle -- confirms the tables are wired up
correctly (FK, unique constraint, defaults) independent of any retrieval
or classification logic.
"""

import pytest
from sqlalchemy.exc import IntegrityError

from app.models import NewsArticle

from .conftest import make_news_article, make_news_source


class TestNewsSource:
    def test_create_with_defaults(self, db):
        news_source = make_news_source(db)
        db.commit()

        assert news_source.enabled is True
        assert news_source.polling_interval_minutes == 60
        assert news_source.consecutive_failures == 0

    def test_connector_field_round_trips(self, db):
        news_source = make_news_source(db, connector="google_news_proxy")
        db.commit()

        assert news_source.connector == "google_news_proxy"


class TestNewsArticle:
    def test_create_linked_to_news_source(self, db):
        news_source = make_news_source(db, name="Ventura Breeze")
        article = make_news_article(db, news_source=news_source, title="City Council Approves Budget")
        db.commit()

        assert article.news_source_id == news_source.id
        assert article.news_source.name == "Ventura Breeze"

    def test_url_must_be_unique(self, db):
        make_news_article(db, url="https://example.invalid/dup")
        db.commit()

        with pytest.raises(IntegrityError):
            make_news_article(db, url="https://example.invalid/dup")
            db.commit()

    def test_topic_categories_defaults_to_empty_list(self, db):
        news_source = make_news_source(db)
        article = NewsArticle(
            news_source_id=news_source.id,
            title="Untagged Article",
            url="https://example.invalid/untagged",
            classification_method="heuristic",
            classification_confidence="low",
        )
        db.add(article)
        db.commit()

        assert article.topic_categories == []
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose run --rm api pytest tests/test_news_models.py -v` (from `cities/ventura/`)
Expected: all PASS. (The `test_engine` fixture's `Base.metadata.create_all(engine)` creates the new tables automatically against `civic_radar_test` — no manual step needed for tests.)

- [ ] **Step 5: Commit**

```bash
git add core/app/models.py core/tests/conftest.py core/tests/test_news_models.py
git commit -m "Add NewsSource/NewsArticle models for the Ventura news feed"
```

---

### Task 2: Feed parsing and classification

**Files:**
- Create: `core/app/news/__init__.py` (empty)
- Create: `core/app/news/feed_parser.py`
- Create: `core/app/news/classify.py`
- Modify: `core/app/ai/prompts.py` (append `NEWS_CLASSIFICATION_PROMPT`)
- Test: `core/tests/test_news_feed_parser.py` (new)
- Test: `core/tests/test_news_classify.py` (new)

**Interfaces:**
- Consumes: `app.ai.prompts.TOPIC_TAXONOMY` (existing list of 25 category strings), `app.ai.ollama_client.is_available()` / `generate_json(model, prompt, timeout=120.0) -> tuple[dict | None, str | None]` (existing), `app.config.settings.project_name` / `settings.ollama_triage_model` (existing).
- Produces: `NewsItem` dataclass (`title: str`, `link: str`, `summary: str | None`, `published_at: datetime | None`) and `parse_feed(xml_bytes: bytes) -> list[NewsItem]`. `classify_article(title: str, summary: str | None, full_text: str | None) -> tuple[list[str], str, str]` returning `(topic_categories, classification_method, classification_confidence)` — Task 3 calls this directly.

- [ ] **Step 1: Write the failing feed-parser tests**

Create `core/tests/test_news_feed_parser.py`:

```python
"""Tests for parse_feed -- covers both feed shapes this pipeline consumes
(WordPress RSS 2.0 and Google News search-RSS), which share the same XML
shape (<item><title>/<link>/<description>/<pubDate>), so one parser
handles both.
"""

from app.news.feed_parser import parse_feed

VALID_RSS = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
<channel>
<title>Test Outlet</title>
<item>
  <title>City Council Approves New Zoning Rules</title>
  <link>https://example.invalid/article-1</link>
  <description>The council voted 4-1 to approve changes.</description>
  <pubDate>Fri, 01 Aug 2026 10:00:00 GMT</pubDate>
</item>
<item>
  <title>Local Bakery Wins Award</title>
  <link>https://example.invalid/article-2</link>
  <description>A feel-good story.</description>
  <pubDate>Thu, 31 Jul 2026 08:30:00 GMT</pubDate>
</item>
</channel>
</rss>"""


class TestParseFeed:
    def test_parses_valid_items(self):
        items = parse_feed(VALID_RSS)

        assert len(items) == 2
        assert items[0].title == "City Council Approves New Zoning Rules"
        assert items[0].link == "https://example.invalid/article-1"
        assert items[0].summary == "The council voted 4-1 to approve changes."
        assert items[0].published_at is not None
        assert items[0].published_at.year == 2026
        assert items[0].published_at.month == 8
        assert items[0].published_at.day == 1

    def test_returns_empty_list_for_malformed_xml(self):
        items = parse_feed(b"not xml at all <<<")

        assert items == []

    def test_skips_items_missing_link(self):
        xml = b"""<rss><channel><item>
          <title>No Link Here</title>
          <description>desc</description>
        </item></channel></rss>"""

        assert parse_feed(xml) == []

    def test_skips_items_missing_title(self):
        xml = b"""<rss><channel><item>
          <link>https://example.invalid/no-title</link>
          <description>desc</description>
        </item></channel></rss>"""

        assert parse_feed(xml) == []

    def test_missing_pub_date_yields_none_not_error(self):
        xml = b"""<rss><channel><item>
          <title>Undated Article</title>
          <link>https://example.invalid/undated</link>
        </item></channel></rss>"""

        items = parse_feed(xml)

        assert len(items) == 1
        assert items[0].published_at is None
        assert items[0].summary is None

    def test_malformed_pub_date_yields_none_not_error(self):
        xml = b"""<rss><channel><item>
          <title>Bad Date Article</title>
          <link>https://example.invalid/bad-date</link>
          <pubDate>not a real date</pubDate>
        </item></channel></rss>"""

        items = parse_feed(xml)

        assert items[0].published_at is None
```

- [ ] **Step 2: Run to verify failure**

Run: `docker compose run --rm api pytest tests/test_news_feed_parser.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.news'`

- [ ] **Step 3: Implement the feed parser**

Create `core/app/news/__init__.py` (empty file).

Create `core/app/news/feed_parser.py`:

```python
"""Parses RSS 2.0 XML into structured news items. Covers both feed shapes
this pipeline consumes -- standard WordPress RSS (wordpress_rss connector)
and Google News search-RSS (google_news_proxy connector) -- both are plain
RSS 2.0 under the hood, so one parser handles both; the connector
distinction only matters to news/retrieval.py, for what happens with the
parsed item afterward (whether a full-text fetch is attempted).
"""

from dataclasses import dataclass
from datetime import datetime
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree


@dataclass
class NewsItem:
    title: str
    link: str
    summary: str | None
    published_at: datetime | None


def parse_feed(xml_bytes: bytes) -> list[NewsItem]:
    try:
        root = ElementTree.fromstring(xml_bytes)
    except ElementTree.ParseError:
        return []

    items: list[NewsItem] = []
    for item in root.iter("item"):
        link = (item.findtext("link") or "").strip()
        title = (item.findtext("title") or "").strip()
        if not link or not title:
            continue
        description = (item.findtext("description") or "").strip() or None
        published_at = _parse_pub_date((item.findtext("pubDate") or "").strip())
        items.append(NewsItem(title=title, link=link, summary=description, published_at=published_at))
    return items


def _parse_pub_date(raw: str) -> datetime | None:
    if not raw:
        return None
    try:
        return parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
```

- [ ] **Step 4: Run feed-parser tests to verify they pass**

Run: `docker compose run --rm api pytest tests/test_news_feed_parser.py -v`
Expected: all PASS

- [ ] **Step 5: Write the failing classification tests**

Create `core/tests/test_news_classify.py`:

```python
"""Tests for classify_article -- heuristic keyword matching runs first;
the AI fallback (same Ollama client as ai/classify.py) only fires when the
heuristic finds nothing. Confidence values follow a fixed rule (see the
design doc): heuristic match -> "medium", successful AI fallback -> "high",
empty/unavailable -> "low".
"""

import app.news.classify as classify_module
from app.news.classify import classify_article, heuristic_classify_article


class TestHeuristicClassifyArticle:
    def test_matches_zoning_keywords(self):
        categories = heuristic_classify_article(
            "City Council Approves New Zoning Rules", "The council voted on a zoning variance.", None
        )

        assert "zoning" in categories

    def test_matches_multiple_categories_ranked_by_hit_count(self):
        categories = heuristic_classify_article(
            "Police Respond to Homeless Encampment Near School",
            "Sheriff deputies and school district officials met about the homeless encampment.",
            None,
        )

        assert "police_public_safety" in categories
        assert "homelessness" in categories
        assert "schools" in categories

    def test_returns_empty_for_unrelated_article(self):
        categories = heuristic_classify_article(
            "Local Bakery Wins National Award", "The bakery's sourdough took first place.", None
        )

        assert categories == []

    def test_considers_full_text_not_just_title_and_summary(self):
        categories = heuristic_classify_article(
            "Community Event This Weekend", "Join us Saturday.", "The event follows the city's new short-term rental ordinance."
        )

        assert "short_term_rentals" in categories


class TestClassifyArticle:
    def test_returns_medium_confidence_when_heuristic_matches(self):
        categories, method, confidence = classify_article(
            "City Council Approves New Zoning Rules", "A zoning variance was granted.", None
        )

        assert categories
        assert method == "heuristic"
        assert confidence == "medium"

    def test_falls_back_to_ai_when_heuristic_finds_nothing(self, monkeypatch):
        monkeypatch.setattr(classify_module.ollama_client, "is_available", lambda: True)
        monkeypatch.setattr(
            classify_module.ollama_client,
            "generate_json",
            lambda model, prompt, **k: ({"topic_categories": ["general_governance"]}, None),
        )

        categories, method, confidence = classify_article("Local Bakery Wins Award", "A feel-good story.", None)

        assert categories == ["general_governance"]
        assert method == "ai"
        assert confidence == "high"

    def test_returns_low_confidence_when_ollama_unavailable(self, monkeypatch):
        monkeypatch.setattr(classify_module.ollama_client, "is_available", lambda: False)

        categories, method, confidence = classify_article("Local Bakery Wins Award", "A feel-good story.", None)

        assert categories == []
        assert method == "heuristic"
        assert confidence == "low"

    def test_returns_low_confidence_when_ollama_call_fails(self, monkeypatch):
        monkeypatch.setattr(classify_module.ollama_client, "is_available", lambda: True)
        monkeypatch.setattr(
            classify_module.ollama_client, "generate_json", lambda model, prompt, **k: (None, "connection refused")
        )

        categories, method, confidence = classify_article("Local Bakery Wins Award", "A feel-good story.", None)

        assert categories == []
        assert method == "heuristic"
        assert confidence == "low"

    def test_drops_ai_categories_not_in_taxonomy(self, monkeypatch):
        monkeypatch.setattr(classify_module.ollama_client, "is_available", lambda: True)
        monkeypatch.setattr(
            classify_module.ollama_client,
            "generate_json",
            lambda model, prompt, **k: ({"topic_categories": ["not_a_real_category"]}, None),
        )

        categories, method, confidence = classify_article("Local Bakery Wins Award", "A feel-good story.", None)

        assert categories == []
        assert method == "heuristic"
        assert confidence == "low"
```

- [ ] **Step 6: Run to verify failure**

Run: `docker compose run --rm api pytest tests/test_news_classify.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.news.classify'`

- [ ] **Step 7: Add the news classification prompt**

Append to `core/app/ai/prompts.py` (after `MEETING_RESULTS_PROMPT` or at the end of the file, wherever the existing prompt constants end):

```python
NEWS_CLASSIFICATION_PROMPT = """You are a civic-news classification assistant for {project_name}.
Classify the following local news article by which civic topics it covers, if any. Be
conservative: if the article is not meaningfully about local government or civic affairs
(e.g. sports, obituaries, entertainment, feel-good human interest), return an empty list
rather than forcing a fit.

Allowed topic_categories (choose 0-3): {taxonomy}

Article title: {title}

Text:
---
{text}
---

Respond with ONLY a JSON object matching this exact shape:
{{
  "topic_categories": ["..."]
}}
"""
```

- [ ] **Step 8: Implement classify.py**

Create `core/app/news/classify.py`:

```python
"""Classifies news articles against the shared civic-topic ontology
(app.ai.prompts.TOPIC_TAXONOMY). Heuristic keyword matching runs first and
covers the common case cheaply; the AI fallback (same Ollama client as
ai/classify.py) only fires when the heuristic finds nothing, keeping
steady-state inference load low at news volume.
"""

from app.ai import ollama_client
from app.ai.prompts import NEWS_CLASSIFICATION_PROMPT, TOPIC_TAXONOMY
from app.config import settings

NEWS_TOPIC_KEYWORDS: dict[str, list[str]] = {
    "land_use": ["land use", "land-use", "general plan", "specific plan"],
    "planning": ["planning commission", "planning department", "site plan", "development plan"],
    "zoning": ["zoning", "rezone", "rezoning", "zone change", "variance"],
    "coastal_development": ["coastal commission", "coastal development permit", "coastal zone", "shoreline"],
    "hillside_development": ["hillside development", "hillside ordinance", "ridgeline"],
    "housing": ["housing", "affordable housing", "apartment complex", "housing element"],
    "ceqa_environment": ["ceqa", "environmental impact report", "environmental review"],
    "public_notice_transparency": ["public records act", "brown act", "public notice", "transparency"],
    "elections": ["election", "ballot measure", "candidate filing", "voter", "primary election"],
    "campaign_finance": ["campaign finance", "campaign contribution", "fppc", "netfile", "campaign donor"],
    "budget_tax_fees": ["city budget", "county budget", "property tax", "sales tax", "budget deficit", "fee increase"],
    "water": ["water district", "water supply", "drought", "water rate", "groundwater"],
    "transportation": ["transportation", "traffic", "bike lane", "metrolink", "vcta", "highway 101", "freeway"],
    "police_public_safety": ["police", "sheriff", "arrest", "crime", "public safety", "fire department"],
    "homelessness": ["homeless", "homelessness", "unhoused", "encampment"],
    "schools": ["school district", "school board", "unified school", "superintendent"],
    "parks_open_space": ["park", "open space", "trail", "recreation area"],
    "cannabis": ["cannabis", "marijuana", "dispensary"],
    "short_term_rentals": ["short-term rental", "short term rental", "airbnb", "vacation rental", "stvr"],
    "public_contracts": ["public contract", "bid award", "request for proposal", "procurement", "contract award"],
    "appointments_commissions": ["appointed to", "commission appointment", "board appointment", "sworn in"],
    "litigation": ["lawsuit", "litigation", "sues", "sued", "legal settlement", "court ruling"],
    "ethics_conflict_of_interest": ["conflict of interest", "ethics complaint", "ethics commission", "recusal"],
    "infrastructure": ["infrastructure", "sewer", "road repair", "bridge", "utility", "pipeline"],
    "general_governance": ["city council", "board of supervisors", "city clerk", "ordinance", "resolution"],
}


def heuristic_classify_article(title: str, summary: str | None, full_text: str | None) -> list[str]:
    haystack = " ".join(filter(None, [title, summary, full_text])).lower()
    scores: dict[str, int] = {}
    for category, keywords in NEWS_TOPIC_KEYWORDS.items():
        count = sum(1 for kw in keywords if kw in haystack)
        if count:
            scores[category] = count
    ranked = sorted(scores.items(), key=lambda pair: pair[1], reverse=True)
    return [category for category, _ in ranked[:3]]


def classify_article(title: str, summary: str | None, full_text: str | None) -> tuple[list[str], str, str]:
    """Returns (topic_categories, classification_method, classification_confidence)."""
    categories = heuristic_classify_article(title, summary, full_text)
    if categories:
        return categories, "heuristic", "medium"

    if not ollama_client.is_available():
        return [], "heuristic", "low"

    text = "\n\n".join(filter(None, [summary, full_text]))
    prompt = NEWS_CLASSIFICATION_PROMPT.format(
        project_name=settings.project_name,
        taxonomy=", ".join(TOPIC_TAXONOMY),
        title=title,
        text=text[:8000],
    )
    output_json, _error = ollama_client.generate_json(settings.ollama_triage_model, prompt)
    if not output_json:
        return [], "heuristic", "low"

    ai_categories = [c for c in output_json.get("topic_categories") or [] if c in TOPIC_TAXONOMY][:3]
    if not ai_categories:
        return [], "heuristic", "low"
    return ai_categories, "ai", "high"
```

- [ ] **Step 9: Run classification tests to verify they pass**

Run: `docker compose run --rm api pytest tests/test_news_classify.py -v`
Expected: all PASS

- [ ] **Step 10: Commit**

```bash
git add core/app/news/__init__.py core/app/news/feed_parser.py core/app/news/classify.py \
        core/app/ai/prompts.py core/tests/test_news_feed_parser.py core/tests/test_news_classify.py
git commit -m "Add RSS feed parsing and heuristic+AI news classification"
```

---

### Task 3: Retrieval orchestration

**Files:**
- Create: `core/app/news/retrieval.py`
- Test: `core/tests/test_news_retrieval.py` (new)

**Interfaces:**
- Consumes: `app.news.feed_parser.parse_feed`, `app.news.classify.classify_article` (Task 2); `app.ingestion.http_client.fetch_url(url, timeout=30.0) -> httpx.Response` (existing); `app.archive.now_utc()`, `sha256_hex(bytes) -> str`, `slugify(str | None, default="misc") -> str`, `write_archive_file(directory: Path, filename: str, content: bytes) -> Path` (existing); `app.parsing.extract.parse_file(path: Path, mime_type: str | None) -> ParsedDocument` (existing — `ParsedDocument.full_text: str`); `app.models.NewsArticle`, `NewsSource` (Task 1).
- Produces: `poll_news_source(db: Session, news_source: NewsSource) -> int` (returns count of new articles created) — Task 4's worker integration calls this directly.

- [ ] **Step 1: Write the failing tests**

Create `core/tests/test_news_retrieval.py`:

```python
"""Tests for poll_news_source -- RSS fetch, dedup by url, per-connector
full-text-fetch behavior, and NewsSource bookkeeping (last_fetched_at/
last_error/consecutive_failures), mirroring the shape of
test_ingestion_pipeline.py's coverage of ingest_source.
"""

import httpx

import app.news.retrieval as retrieval_module
from app.models import NewsArticle
from app.news.retrieval import poll_news_source

from .conftest import make_news_source

RSS_ONE_ITEM = b"""<?xml version="1.0"?>
<rss><channel>
<item>
  <title>City Council Approves New Zoning Rules</title>
  <link>https://example.invalid/article-1</link>
  <description>The council voted on a zoning variance.</description>
  <pubDate>Fri, 01 Aug 2026 10:00:00 GMT</pubDate>
</item>
</channel></rss>"""

RSS_TWO_ITEMS = b"""<?xml version="1.0"?>
<rss><channel>
<item>
  <title>City Council Approves New Zoning Rules</title>
  <link>https://example.invalid/article-1</link>
  <description>The council voted on a zoning variance.</description>
</item>
<item>
  <title>Local Bakery Wins Award</title>
  <link>https://example.invalid/article-2</link>
  <description>A feel-good story.</description>
</item>
</channel></rss>"""


def fake_response(content: bytes, status_code: int = 200) -> httpx.Response:
    return httpx.Response(status_code=status_code, content=content)


class TestPollNewsSourceBookkeeping:
    def test_success_updates_last_fetched_at_and_clears_errors(self, db, archive_root, monkeypatch):
        news_source = make_news_source(db, connector="google_news_proxy", last_error="old error", consecutive_failures=3)
        monkeypatch.setattr(retrieval_module, "fetch_url", lambda url, **k: fake_response(RSS_ONE_ITEM))

        poll_news_source(db, news_source)

        assert news_source.last_fetched_at is not None
        assert news_source.last_error is None
        assert news_source.consecutive_failures == 0

    def test_feed_fetch_failure_records_error_and_increments_failures(self, db, archive_root, monkeypatch):
        news_source = make_news_source(db, connector="google_news_proxy")

        def raise_error(url, **kwargs):
            raise httpx.ConnectError("connection refused")

        monkeypatch.setattr(retrieval_module, "fetch_url", raise_error)

        created = poll_news_source(db, news_source)

        assert created == 0
        assert news_source.consecutive_failures == 1
        assert "connection refused" in news_source.last_error
        assert news_source.last_fetched_at is not None


class TestPollNewsSourceDedup:
    def test_creates_new_articles_from_feed(self, db, archive_root, monkeypatch):
        news_source = make_news_source(db, connector="google_news_proxy")
        monkeypatch.setattr(retrieval_module, "fetch_url", lambda url, **k: fake_response(RSS_TWO_ITEMS))

        created = poll_news_source(db, news_source)

        assert created == 2
        assert db.query(NewsArticle).count() == 2

    def test_skips_urls_already_seen(self, db, archive_root, monkeypatch):
        news_source = make_news_source(db, connector="google_news_proxy")
        monkeypatch.setattr(retrieval_module, "fetch_url", lambda url, **k: fake_response(RSS_ONE_ITEM))

        first = poll_news_source(db, news_source)
        db.commit()
        second = poll_news_source(db, news_source)

        assert first == 1
        assert second == 0
        assert db.query(NewsArticle).count() == 1


class TestGoogleNewsProxyNeverFetchesArticlePage:
    def test_full_text_and_archive_path_stay_none(self, db, archive_root, monkeypatch):
        news_source = make_news_source(db, connector="google_news_proxy")
        calls = []

        def tracking_fetch(url, **kwargs):
            calls.append(url)
            return fake_response(RSS_ONE_ITEM)

        monkeypatch.setattr(retrieval_module, "fetch_url", tracking_fetch)

        poll_news_source(db, news_source)

        # Only the feed URL was ever fetched -- never the article link.
        assert calls == [news_source.rss_feed_url]
        article = db.query(NewsArticle).one()
        assert article.full_text is None
        assert article.archive_path is None


class TestWordpressRssFullTextFetch:
    def test_extracts_full_text_on_success(self, db, archive_root, monkeypatch):
        news_source = make_news_source(db, connector="wordpress_rss")

        def fetch_by_url(url, **kwargs):
            if url == news_source.rss_feed_url:
                return fake_response(RSS_ONE_ITEM)
            return fake_response(b"<html><body><p>Full article body text.</p></body></html>")

        monkeypatch.setattr(retrieval_module, "fetch_url", fetch_by_url)

        poll_news_source(db, news_source)

        article = db.query(NewsArticle).one()
        assert article.full_text is not None
        assert "Full article body text." in article.full_text
        assert article.archive_path is not None

    def test_falls_back_to_summary_when_article_fetch_fails(self, db, archive_root, monkeypatch):
        news_source = make_news_source(db, connector="wordpress_rss")

        def fetch_by_url(url, **kwargs):
            if url == news_source.rss_feed_url:
                return fake_response(RSS_ONE_ITEM)
            raise httpx.ConnectError("article page unreachable")

        monkeypatch.setattr(retrieval_module, "fetch_url", fetch_by_url)

        created = poll_news_source(db, news_source)

        assert created == 1
        article = db.query(NewsArticle).one()
        assert article.full_text is None
        assert article.archive_path is None
        assert article.summary == "The council voted on a zoning variance."
```

- [ ] **Step 2: Run to verify failure**

Run: `docker compose run --rm api pytest tests/test_news_retrieval.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.news.retrieval'`

- [ ] **Step 3: Implement retrieval.py**

Create `core/app/news/retrieval.py`:

```python
"""Polls a NewsSource's RSS feed, archives new articles, and classifies
them against the civic-topic ontology. Kept in its own core/app/news/
package -- not ingestion/ -- so this pipeline stays visibly decoupled
from the government-document Source/Fetch/Document flow.
"""

import logging
from pathlib import Path

import httpx
from sqlalchemy.orm import Session

from app.archive import now_utc, sha256_hex, slugify, write_archive_file
from app.config import settings
from app.ingestion.http_client import fetch_url
from app.models import NewsArticle, NewsSource
from app.news.classify import classify_article
from app.news.feed_parser import NewsItem, parse_feed
from app.parsing.extract import parse_file

logger = logging.getLogger(__name__)


def poll_news_source(db: Session, news_source: NewsSource) -> int:
    """Fetches news_source's feed, archives+classifies new items, updates
    bookkeeping fields. Returns the count of new NewsArticle rows created.
    """
    try:
        response = fetch_url(news_source.rss_feed_url)
    except httpx.HTTPError as exc:
        news_source.last_error = str(exc)[:2000]
        news_source.consecutive_failures += 1
        news_source.last_fetched_at = now_utc()
        db.commit()
        logger.warning("news feed fetch failed for %s: %s", news_source.name, exc)
        return 0

    items = parse_feed(response.content)
    new_count = 0
    for item in items:
        already_seen = db.query(NewsArticle.id).filter(NewsArticle.url == item.link).first()
        if already_seen:
            continue
        _archive_and_save(db, news_source, item)
        new_count += 1

    news_source.last_error = None
    news_source.consecutive_failures = 0
    news_source.last_fetched_at = now_utc()
    db.commit()
    return new_count


def _archive_and_save(db: Session, news_source: NewsSource, item: NewsItem) -> NewsArticle:
    full_text: str | None = None
    archive_path: str | None = None

    if news_source.connector == "wordpress_rss":
        full_text, archive_path = _fetch_and_extract(news_source.name, item.link)

    categories, method, confidence = classify_article(item.title, item.summary, full_text)

    article = NewsArticle(
        news_source_id=news_source.id,
        title=item.title,
        url=item.link,
        published_at=item.published_at,
        summary=item.summary,
        full_text=full_text,
        archive_path=archive_path,
        topic_categories=categories,
        classification_method=method,
        classification_confidence=confidence,
    )
    db.add(article)
    db.flush()
    return article


def _fetch_and_extract(outlet_name: str, article_url: str) -> tuple[str | None, str | None]:
    try:
        response = fetch_url(article_url)
    except httpx.HTTPError as exc:
        logger.info("news article fetch failed for %s: %s", article_url, exc)
        return None, None

    body = response.content
    page_hash = sha256_hex(body)
    when = now_utc()
    directory = (
        Path(settings.archive_root) / "news" / slugify(outlet_name) / str(when.year) / when.strftime("%Y-%m-%d")
    )
    path = write_archive_file(directory, f"article_{page_hash[:12]}.html", body)

    try:
        parsed = parse_file(path, "text/html")
    except Exception:
        logger.info("news article text extraction failed for %s", article_url)
        return None, str(path)

    return parsed.full_text, str(path)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose run --rm api pytest tests/test_news_retrieval.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add core/app/news/retrieval.py core/tests/test_news_retrieval.py
git commit -m "Add news retrieval orchestration: fetch, dedup, archive, classify"
```

---

### Task 4: API endpoint and worker integration

**Files:**
- Create: `core/app/routers/news.py`
- Modify: `core/app/schemas.py` (append `NewsArticleOut`)
- Modify: `core/app/main.py` (register `news` router)
- Modify: `core/app/worker.py` (add `run_news_batch`, wire into `tick()`)
- Test: `core/tests/test_router_news.py` (new)
- Test: `core/tests/test_worker.py` (add `TestRunNewsBatch`, extend `TestTick`)

**Interfaces:**
- Consumes: `app.news.retrieval.poll_news_source` (Task 3), `app.models.NewsSource`/`NewsArticle` (Task 1), `app.worker.is_due(source, now) -> bool` (existing — works structurally with `NewsSource` since it only reads `.last_fetched_at`/`.polling_interval_minutes`, no `isinstance` check).
- Produces: `GET /api/news` endpoint; `run_news_batch() -> None` in `worker.py`.

- [ ] **Step 1: Add the schema**

In `core/app/schemas.py`, append after `LogEntryOut`:

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

- [ ] **Step 2: Write the failing router tests**

Create `core/tests/test_router_news.py`:

```python
"""Tests for /api/news -- topic/outlet filtering and before-cursor
pagination, mirroring test_router_logs.py's conventions.
"""

from datetime import timedelta

from .conftest import make_news_article, make_news_source, utcnow


class TestListNews:
    def test_returns_articles_with_outlet_name(self, client, db):
        news_source = make_news_source(db, name="Ventura Breeze")
        make_news_article(db, news_source=news_source, title="City Council Meets")
        db.commit()

        resp = client.get("/api/news")

        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 1
        assert body[0]["title"] == "City Council Meets"
        assert body[0]["outlet_name"] == "Ventura Breeze"

    def test_filters_by_topic(self, client, db):
        make_news_article(db, title="Zoning Article", topic_categories=["zoning"])
        make_news_article(db, title="Unrelated Article", topic_categories=["schools"])
        db.commit()

        resp = client.get("/api/news?topic=zoning")

        body = resp.json()
        assert len(body) == 1
        assert body[0]["title"] == "Zoning Article"

    def test_filters_by_source_id(self, client, db):
        source_a = make_news_source(db, name="Outlet A")
        source_b = make_news_source(db, name="Outlet B")
        make_news_article(db, news_source=source_a, title="From A")
        make_news_article(db, news_source=source_b, title="From B")
        db.commit()

        resp = client.get(f"/api/news?source_id={source_a.id}")

        body = resp.json()
        assert len(body) == 1
        assert body[0]["title"] == "From A"

    def test_before_cursor_pagination(self, client, db):
        now = utcnow()
        make_news_article(db, title="Older", published_at=now - timedelta(days=2))
        make_news_article(db, title="Newer", published_at=now)
        db.commit()

        resp = client.get(f"/api/news?before={now.isoformat()}")

        body = resp.json()
        assert len(body) == 1
        assert body[0]["title"] == "Older"

    def test_malformed_source_id_returns_400_not_500(self, client, db):
        resp = client.get("/api/news?source_id=not-a-uuid")

        assert resp.status_code == 400

    def test_malformed_before_returns_400_not_500(self, client, db):
        resp = client.get("/api/news?before=not-a-date")

        assert resp.status_code == 400
```

- [ ] **Step 3: Run to verify failure**

Run: `docker compose run --rm api pytest tests/test_router_news.py -v`
Expected: FAIL with `404` responses (router doesn't exist yet) / import errors once schema is referenced.

- [ ] **Step 4: Implement the router**

Create `core/app/routers/news.py`:

```python
"""Read-only feed over classified NewsArticle rows -- topic/outlet
filtering and before-cursor pagination. Deliberately has no `after`
param (unlike /api/logs): the News tab does not auto-poll, so there's no
"give me anything newer than X" use case.
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import NewsArticle, NewsSource
from app.schemas import NewsArticleOut

router = APIRouter(prefix="/api/news", tags=["news"])


def _parse_source_id(raw: str | None) -> uuid.UUID | None:
    return None if raw in (None, "all") else uuid.UUID(raw)


@router.get("", response_model=list[NewsArticleOut])
def list_news(
    topic: str = Query(default="all"),
    source_id: str | None = Query(default=None),
    before: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> list[NewsArticleOut]:
    try:
        parsed_source_id = _parse_source_id(source_id)
        parsed_before = datetime.fromisoformat(before) if before else None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"invalid query parameter: {exc}") from exc

    q = db.query(NewsArticle, NewsSource.name).join(NewsSource, NewsArticle.news_source_id == NewsSource.id)
    if topic != "all":
        q = q.filter(NewsArticle.topic_categories.any(topic))
    if parsed_source_id is not None:
        q = q.filter(NewsArticle.news_source_id == parsed_source_id)
    if parsed_before is not None:
        q = q.filter(NewsArticle.published_at < parsed_before)
    q = q.order_by(NewsArticle.published_at.desc().nullslast()).limit(limit)

    results = []
    for article, outlet_name in q.all():
        results.append(
            NewsArticleOut(
                id=str(article.id),
                title=article.title,
                url=article.url,
                outlet_name=outlet_name,
                published_at=article.published_at,
                summary=article.summary,
                topic_categories=article.topic_categories,
                classification_method=article.classification_method,
                classification_confidence=article.classification_confidence,
            )
        )
    return results
```

- [ ] **Step 5: Register the router**

In `core/app/main.py`, add `news` to the `from app.routers import (...)` block (alphabetical) and add `app.include_router(news.router)` — place it next to `app.include_router(logs.router)`, before `app.include_router(dashboard.router)`.

- [ ] **Step 6: Run router tests to verify they pass**

Run: `docker compose run --rm api pytest tests/test_router_news.py -v`
Expected: all PASS

- [ ] **Step 7: Write the failing worker tests**

In `core/tests/test_worker.py`, add near the existing `TestTick`/throttle-related classes (add the import `from app.news.retrieval import poll_news_source` is NOT needed in the test file — the test monkeypatches `worker_module.poll_news_source`):

```python
class TestRunNewsBatch:
    def test_polls_due_news_sources(self, db, db_session_factory, monkeypatch):
        monkeypatch.setattr(worker_module, "SessionLocal", db_session_factory)
        news_source = make_news_source(db, enabled=True)
        db.commit()
        calls = []
        monkeypatch.setattr(worker_module, "poll_news_source", lambda db, ns: calls.append(ns.id) or 0)

        worker_module.run_news_batch()

        assert calls == [news_source.id]

    def test_skips_not_due_news_sources(self, db, db_session_factory, monkeypatch):
        monkeypatch.setattr(worker_module, "SessionLocal", db_session_factory)
        make_news_source(db, enabled=True, last_fetched_at=now_utc(), polling_interval_minutes=60)
        db.commit()
        calls = []
        monkeypatch.setattr(worker_module, "poll_news_source", lambda db, ns: calls.append(ns.id) or 0)

        worker_module.run_news_batch()

        assert calls == []

    def test_skips_disabled_news_sources(self, db, db_session_factory, monkeypatch):
        monkeypatch.setattr(worker_module, "SessionLocal", db_session_factory)
        make_news_source(db, enabled=False)
        db.commit()
        calls = []
        monkeypatch.setattr(worker_module, "poll_news_source", lambda db, ns: calls.append(ns.id) or 0)

        worker_module.run_news_batch()

        assert calls == []

    def test_crash_is_caught_and_logged_without_source_id(self, db, db_session_factory, monkeypatch):
        monkeypatch.setattr(worker_module, "SessionLocal", db_session_factory)
        make_news_source(db, enabled=True)
        db.commit()

        def raise_error(db, ns):
            raise RuntimeError("boom")

        monkeypatch.setattr(worker_module, "poll_news_source", raise_error)

        worker_module.run_news_batch()  # must not raise
```

Add the import at the top of `test_worker.py`'s existing `from .conftest import (...)` block: `make_news_source`.

Update `TestTick::test_runs_all_three_batches_in_order` (rename in place, it now covers four batches) to also monkeypatch and assert `run_news_batch`:

```python
class TestTick:
    def test_runs_all_batches_in_order(self, db_session_factory, monkeypatch):
        monkeypatch.setattr(worker_module, "SessionLocal", db_session_factory)
        calls = []
        monkeypatch.setattr(worker_module, "run_ingestion_tick", lambda: calls.append("ingestion"))
        monkeypatch.setattr(worker_module, "run_parsing_batch", lambda: calls.append("parsing"))
        monkeypatch.setattr(worker_module, "run_ai_batch", lambda: calls.append("ai"))
        monkeypatch.setattr(worker_module, "run_news_batch", lambda: calls.append("news"))
        monkeypatch.setattr(worker_module, "maybe_prune_app_logs", lambda: calls.append("prune"))

        worker_module.tick()

        assert calls == ["ingestion", "parsing", "ai", "news", "prune"]
```

(This replaces the existing test body — it previously didn't monkeypatch `maybe_prune_app_logs`, relying on the real one running harmlessly; making it explicit here keeps the ordering assertion exact now that a fifth step exists.)

- [ ] **Step 8: Run to verify failure**

Run: `docker compose run --rm api pytest tests/test_worker.py -v -k "RunNewsBatch or runs_all_batches"`
Expected: FAIL — `AttributeError: module 'app.worker' has no attribute 'run_news_batch'` (and the renamed test fails to collect under its old name if referenced elsewhere — it isn't).

- [ ] **Step 9: Implement run_news_batch and wire it into tick()**

In `core/app/worker.py`:

Add imports (alongside the existing ones, alphabetically among the `app.*` imports):

```python
from app.models import AiOutput, Document, NewsSource, Source
from app.news.retrieval import poll_news_source
```

(This changes the existing `from app.models import AiOutput, Document, Source` line to include `NewsSource`.)

Add the function after `run_ai_batch()`:

```python
def run_news_batch() -> None:
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        news_sources = db.query(NewsSource).filter(NewsSource.enabled.is_(True)).all()
        for news_source in news_sources:
            if not is_due(news_source, now):
                continue
            try:
                poll_news_source(db, news_source)
            except Exception:
                db.rollback()
                logger.exception("news polling crashed for source %s", news_source.name)
    finally:
        db.close()
```

Update `tick()`:

```python
def tick() -> None:
    run_ingestion_tick()
    run_parsing_batch()
    run_ai_batch()
    run_news_batch()
    maybe_prune_app_logs()
```

- [ ] **Step 10: Run worker tests to verify they pass**

Run: `docker compose run --rm api pytest tests/test_worker.py -v`
Expected: all PASS

- [ ] **Step 11: Run the full test suite**

Run: `docker compose run --rm api pytest -v`
Expected: all PASS (confirms no regressions in the existing 579+ tests)

- [ ] **Step 12: Commit**

```bash
git add core/app/routers/news.py core/app/schemas.py core/app/main.py core/app/worker.py \
        core/tests/test_router_news.py core/tests/test_worker.py
git commit -m "Add /api/news endpoint and worker news-polling batch"
```

---

### Task 5: Dashboard UI

**Files:**
- Modify: `core/app/dashboard.py` (add `news_page` route)
- Create: `core/app/templates/news.html`
- Modify: `core/app/templates/base.html` (add nav link)
- Test: `core/tests/test_api_smoke.py` (add News page smoke tests)

**Interfaces:**
- Consumes: `GET /api/news` (Task 4), `app.models.NewsSource` (Task 1).
- Produces: `GET /news` page.

- [ ] **Step 1: Write the failing smoke tests**

In `core/tests/test_api_smoke.py`, add to the `TestDashboardPages` class (matching the existing `test_logs_page_renders_with_empty_database` / `test_logs_page_renders_with_sources` pair):

```python
    def test_news_page_renders_with_empty_database(self, client):
        resp = client.get("/news")

        assert resp.status_code == 200

    def test_news_page_renders_with_news_sources(self, client, db):
        make_news_source(db, name="Ventura Breeze")
        db.commit()

        resp = client.get("/news")

        assert resp.status_code == 200
        assert "Ventura Breeze" in resp.text
```

Add to the `TestHealthAndApi` class (matching `test_logs_api_empty`):

```python
    def test_news_api_empty(self, client):
        resp = client.get("/api/news")

        assert resp.status_code == 200
        assert resp.json() == []
```

Add `make_news_source` to this test file's `from .conftest import (...)` block.

- [ ] **Step 2: Run to verify failure**

Run: `docker compose run --rm api pytest tests/test_api_smoke.py -v -k news`
Expected: FAIL with `404` (no `/news` route yet)

- [ ] **Step 3: Add the dashboard route**

In `core/app/dashboard.py`, add after `logs_page` (and add `NewsSource` to the existing `from app.models import (...)` block):

```python
@router.get("/news")
def news_page(request: Request, db: Session = Depends(get_db)):
    news_sources = db.query(NewsSource).order_by(NewsSource.name).all()
    return templates.TemplateResponse("news.html", {"request": request, "news_sources": news_sources})
```

- [ ] **Step 4: Create the template**

Create `core/app/templates/news.html`:

```html
{% extends "base.html" %}
{% block title %}News — {{ project_name }}{% endblock %}
{% block content %}
<h1>News</h1>
<div class="panel">
  <label style="display:inline-block;margin-right:1.5rem;">Topic
    <select id="news-topic">
      <option value="all">All topics</option>
      <option value="land_use">Land Use</option>
      <option value="planning">Planning</option>
      <option value="zoning">Zoning</option>
      <option value="coastal_development">Coastal Development</option>
      <option value="hillside_development">Hillside Development</option>
      <option value="housing">Housing</option>
      <option value="ceqa_environment">CEQA / Environment</option>
      <option value="public_notice_transparency">Public Notice / Transparency</option>
      <option value="elections">Elections</option>
      <option value="campaign_finance">Campaign Finance</option>
      <option value="budget_tax_fees">Budget / Tax / Fees</option>
      <option value="water">Water</option>
      <option value="transportation">Transportation</option>
      <option value="police_public_safety">Police / Public Safety</option>
      <option value="homelessness">Homelessness</option>
      <option value="schools">Schools</option>
      <option value="parks_open_space">Parks / Open Space</option>
      <option value="cannabis">Cannabis</option>
      <option value="short_term_rentals">Short-Term Rentals</option>
      <option value="public_contracts">Public Contracts</option>
      <option value="appointments_commissions">Appointments / Commissions</option>
      <option value="litigation">Litigation</option>
      <option value="ethics_conflict_of_interest">Ethics / Conflict of Interest</option>
      <option value="infrastructure">Infrastructure</option>
      <option value="general_governance">General Governance</option>
    </select>
  </label>
  <label style="display:inline-block;">Outlet
    <select id="news-source">
      <option value="all">All outlets</option>
      {% for s in news_sources %}
      <option value="{{ s.id }}">{{ s.name }}</option>
      {% endfor %}
    </select>
  </label>
</div>
<table>
  <thead>
    <tr><th>Published</th><th>Headline</th><th>Outlet</th><th>Topics</th></tr>
  </thead>
  <tbody id="news-rows"></tbody>
</table>
<p class="empty" id="news-empty" style="display:none;">No articles match this filter.</p>
<p class="empty" id="news-error" style="display:none;color:#d9534f;"></p>
<p><button type="button" class="secondary" id="news-load-more">Load more</button></p>

<script>
(function () {
  var rowsEl = document.getElementById('news-rows');
  var topicSel = document.getElementById('news-topic');
  var sourceSel = document.getElementById('news-source');
  var loadMoreBtn = document.getElementById('news-load-more');
  var emptyEl = document.getElementById('news-empty');
  var errorEl = document.getElementById('news-error');

  var oldestPublishedAt = null;

  function renderRow(article) {
    var tr = document.createElement('tr');

    var tdTime = document.createElement('td');
    tdTime.className = 'muted';
    tdTime.textContent = article.published_at ? new Date(article.published_at).toLocaleDateString() : 'undated';
    tr.appendChild(tdTime);

    var tdHeadline = document.createElement('td');
    if (article.summary) {
      var details = document.createElement('details');
      var summaryEl = document.createElement('summary');
      var link = document.createElement('a');
      link.className = 'link';
      link.href = article.url;
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
      link.textContent = article.title;
      summaryEl.appendChild(link);
      details.appendChild(summaryEl);
      var p = document.createElement('p');
      p.className = 'muted';
      p.textContent = article.summary;
      details.appendChild(p);
      tdHeadline.appendChild(details);
    } else {
      var plainLink = document.createElement('a');
      plainLink.className = 'link';
      plainLink.href = article.url;
      plainLink.target = '_blank';
      plainLink.rel = 'noopener noreferrer';
      plainLink.textContent = article.title;
      tdHeadline.appendChild(plainLink);
    }
    tr.appendChild(tdHeadline);

    var tdOutlet = document.createElement('td');
    tdOutlet.className = 'muted';
    tdOutlet.textContent = article.outlet_name;
    tr.appendChild(tdOutlet);

    var tdTopics = document.createElement('td');
    article.topic_categories.forEach(function (topic) {
      var badge = document.createElement('span');
      badge.className = 'badge level-2';
      badge.style.marginRight = '0.3rem';
      badge.textContent = topic;
      tdTopics.appendChild(badge);
    });
    tr.appendChild(tdTopics);

    rowsEl.appendChild(tr);
  }

  function buildUrl(extraParams) {
    var params = { topic: topicSel.value, source_id: sourceSel.value };
    for (var key in extraParams) {
      params[key] = extraParams[key];
    }
    var query = Object.keys(params)
      .filter(function (k) { return params[k] !== null && params[k] !== undefined; })
      .map(function (k) { return encodeURIComponent(k) + '=' + encodeURIComponent(params[k]); })
      .join('&');
    return '/api/news?' + query;
  }

  function updateOldestFromEntries(articles) {
    articles.forEach(function (article) {
      if (!article.published_at) return;
      if (oldestPublishedAt === null || new Date(article.published_at).getTime() < new Date(oldestPublishedAt).getTime()) {
        oldestPublishedAt = article.published_at;
      }
    });
  }

  function loadInitial() {
    errorEl.style.display = 'none';
    fetch(buildUrl({}))
      .then(function (r) {
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.json();
      })
      .then(function (articles) {
        rowsEl.innerHTML = '';
        oldestPublishedAt = null;
        articles.forEach(renderRow);
        updateOldestFromEntries(articles);
        emptyEl.style.display = articles.length === 0 ? 'block' : 'none';
        errorEl.style.display = 'none';
      })
      .catch(function (err) {
        console.error('News fetch failed:', err);
        errorEl.textContent = 'Failed to load news';
        errorEl.style.display = 'block';
        emptyEl.style.display = 'none';
      });
  }

  function loadMore() {
    if (oldestPublishedAt === null) return;
    fetch(buildUrl({ before: oldestPublishedAt }))
      .then(function (r) {
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.json();
      })
      .then(function (articles) {
        articles.forEach(renderRow);
        updateOldestFromEntries(articles);
        errorEl.style.display = 'none';
      })
      .catch(function (err) {
        console.error('News load-more failed:', err);
        errorEl.textContent = 'Failed to load more news';
        errorEl.style.display = 'block';
      });
  }

  topicSel.addEventListener('change', loadInitial);
  sourceSel.addEventListener('change', loadInitial);
  loadMoreBtn.addEventListener('click', loadMore);

  loadInitial();
})();
</script>
{% endblock %}
```

- [ ] **Step 5: Add the nav link**

In `core/app/templates/base.html`, add `<a href="/news">News</a>` immediately after `<a href="/logs">Logs</a>`.

- [ ] **Step 6: Run smoke tests to verify they pass**

Run: `docker compose run --rm api pytest tests/test_api_smoke.py -v -k news`
Expected: all PASS

- [ ] **Step 7: Run the full test suite**

Run: `docker compose run --rm api pytest -v`
Expected: all PASS

- [ ] **Step 8: Commit**

```bash
git add core/app/dashboard.py core/app/templates/news.html core/app/templates/base.html \
        core/tests/test_api_smoke.py
git commit -m "Add News dashboard tab: /news page and topic/outlet filtering"
```

---

### Task 6: Seed Ventura outlets and roll out

**Files:**
- Create: `cities/ventura/seed_news_sources.py`
- Modify: `cities/ventura/docker-compose.yml` (bind-mount the new seed script, same pattern as `seed_sources.py`)

**Interfaces:**
- Consumes: `app.models.NewsSource`, `app.db.SessionLocal` (existing).
- Produces: nothing new consumed by later tasks — this is the terminal task.

- [ ] **Step 1: Verify each candidate feed is still live**

Before writing the seed list, re-verify each URL below actually returns a valid RSS/XML feed (feeds can go stale between design and implementation). For each, run (from any machine with network access — this is a manual verification step, not a test):

```bash
curl -s -o /dev/null -w "%{http_code} %{content_type}\n" "<feed_url>"
```

Candidates to verify:
- `https://venturabreeze.com/feed/` (confirmed live during design)
- `https://www.thecamarilloacorn.com/feed/` (confirmed live during design)
- `https://www.theacorn.com/feed/` (confirmed live during design)
- `https://www.simivalleyacorn.com/feed/`
- `https://www.mpacorn.com/feed/`
- `https://www.toacorn.com/feed/`
- `https://www.ojaivalleynews.com/feed/` (404'd once during design, rate-limited on retry — check carefully; if no working feed is found, drop this outlet from the seed list rather than guess a URL)
- `https://news.google.com/rss/search?q=site%3Avcstar.com&hl=en-US&gl=US&ceid=US%3Aen` (confirmed live during design; connector `google_news_proxy`)

Drop any outlet whose feed doesn't verify live — do not seed a URL that wasn't confirmed working, per `seed_sources.py`'s existing "verified live" convention.

- [ ] **Step 2: Write the seed script**

Create `cities/ventura/seed_news_sources.py`, following `cities/ventura/seed_sources.py`'s structure exactly (docstring, `SOURCES` list of dicts, idempotent `main()` matching by URL). Use the verified subset from Step 1 — the block below assumes all candidates verified live; remove any that didn't:

```python
"""Seed the news-source registry with Ventura County local outlets whose
RSS feeds were verified live (see docs/superpowers/specs/
2026-08-01-ventura-news-feed-design.md). Safe to re-run -- existing rows
are matched by rss_feed_url and left alone rather than duplicated.
"""

from app.db import SessionLocal
from app.models import NewsSource

NEWS_SOURCES = [
    dict(
        name="Ventura Breeze",
        outlet_url="https://venturabreeze.com/",
        rss_feed_url="https://venturabreeze.com/feed/",
        connector="wordpress_rss",
    ),
    dict(
        name="The Camarillo Acorn",
        outlet_url="https://www.thecamarilloacorn.com/",
        rss_feed_url="https://www.thecamarilloacorn.com/feed/",
        connector="wordpress_rss",
    ),
    dict(
        name="The Acorn",
        outlet_url="https://www.theacorn.com/",
        rss_feed_url="https://www.theacorn.com/feed/",
        connector="wordpress_rss",
    ),
    dict(
        name="Simi Valley Acorn",
        outlet_url="https://www.simivalleyacorn.com/",
        rss_feed_url="https://www.simivalleyacorn.com/feed/",
        connector="wordpress_rss",
    ),
    dict(
        name="Moorpark Acorn",
        outlet_url="https://www.mpacorn.com/",
        rss_feed_url="https://www.mpacorn.com/feed/",
        connector="wordpress_rss",
    ),
    dict(
        name="Thousand Oaks Acorn",
        outlet_url="https://www.toacorn.com/",
        rss_feed_url="https://www.toacorn.com/feed/",
        connector="wordpress_rss",
    ),
    dict(
        name="Ventura County Star",
        outlet_url="https://www.vcstar.com/",
        rss_feed_url="https://news.google.com/rss/search?q=site%3Avcstar.com&hl=en-US&gl=US&ceid=US%3Aen",
        connector="google_news_proxy",
    ),
]


def main() -> None:
    db = SessionLocal()
    try:
        created = 0
        for row in NEWS_SOURCES:
            existing = db.query(NewsSource).filter(NewsSource.rss_feed_url == row["rss_feed_url"]).one_or_none()
            if existing:
                continue
            db.add(NewsSource(**row))
            created += 1
        db.commit()
        print(f"Seeded {created} new news source(s).")
    finally:
        db.close()


if __name__ == "__main__":
    main()
```

(Omit the `Ojai Valley News` entry unless Step 1 confirms a working feed URL for it.)

- [ ] **Step 3: Bind-mount the seed script**

In `cities/ventura/docker-compose.yml`, the `api` service already bind-mounts the city's own `seed_sources.py` over the shared image's `scripts/` path:

```yaml
    volumes:
      - ./archive:/archive
      - ../../core:/app
      - ./city_settings.py:/app/app/city_config.py
      - ./seed_sources.py:/app/scripts/seed_sources.py
```

Add one line, mirroring that exact pattern:

```yaml
      - ./seed_news_sources.py:/app/scripts/seed_news_sources.py
```

(`worker`'s volumes block does not need this — seeding is a manual one-off run against `api`, same as `seed_sources.py`/`seed_prompts.py` today.)

- [ ] **Step 4: Commit**

```bash
git add cities/ventura/seed_news_sources.py cities/ventura/docker-compose.yml
git commit -m "Seed Ventura County news outlet sources"
```

- [ ] **Step 5: Rollout (not a commit — live-database step)**

Once this plan's final whole-branch review is clean and the branch is merged (per `finishing-a-development-branch`), from `cities/ventura/`:

1. `docker compose up -d api` (or restart it) to pick up the docker-compose.yml volume change from Step 3.
2. `docker compose run --rm api python scripts/init_db.py` against Ventura's live database — creates `news_sources`/`news_articles` (additive, safe, matches the Logs-tab rollout precedent).
3. `docker compose run --rm api python scripts/seed_news_sources.py` — same invocation pattern as `docker compose run --rm api python scripts/seed_sources.py` (documented in `cities/ventura/README.md`) — populates the outlet rows.
4. `docker compose restart worker` — picks up `run_news_batch` in its tick loop.
5. Smoke-test `/news` and `/api/news` return 200 on Ventura's dashboard port (8010).
