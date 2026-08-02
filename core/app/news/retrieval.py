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

# Local WordPress RSS feeds each carry only their own ~10-20 latest items, so
# this cap is about bounding one source's per-poll work if a feed is unusually
# large, not backfill pacing -- items beyond the cap are simply picked up on
# the next poll (they're not yet in the DB, so they aren't skipped as dupes).
MAX_NEW_ARTICLES_PER_POLL = 20

# Google News's `site:` search (the google_news_proxy connector) indexes an
# outlet's whole domain, not just its posts, so it can surface static
# navigation/utility pages alongside real articles -- e.g. "Advertise - The
# Fillmore Gazette" or "Santa Paula Times - Santa Paula Times" (the outlet's
# own masthead page). Filter title patterns that are clearly not real
# headlines: a short, generic site-chrome label, or a headline that repeats
# the outlet's own name (something a real news headline essentially never
# does). This is a heuristic, not exhaustive -- an outlet-specific section
# front with an unrecognized label (e.g. a "Locales" section index) can
# still slip through; the goal is cutting the clear majority of noise, not
# perfect precision.
NON_ARTICLE_TITLE_LABELS = {
    "advertise",
    "subscribe",
    "copyright",
    "help",
    "suggestions",
    "user agreement",
    "news",
    "obituaries",
    "contact",
    "contact us",
    "about",
    "about us",
    "terms",
    "terms of service",
    "privacy",
    "privacy policy",
    "home",
}


def _looks_like_non_article(title: str, outlet_name: str) -> bool:
    label = title
    suffix = f" - {outlet_name}"
    if label.lower().endswith(suffix.lower()):
        label = label[: -len(suffix)]
    label = label.strip().lower()
    if label in NON_ARTICLE_TITLE_LABELS:
        return True
    return outlet_name.lower() in label


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
        if new_count >= MAX_NEW_ARTICLES_PER_POLL:
            break
        already_seen = db.query(NewsArticle.id).filter(NewsArticle.url == item.link).first()
        if already_seen:
            continue
        if _looks_like_non_article(item.title, news_source.name):
            continue
        try:
            _archive_and_save(db, news_source, item)
        except Exception:
            db.rollback()
            logger.exception("failed to archive/classify article %s for source %s", item.link, news_source.name)
            continue
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
        if item.content_encoded:
            # Prefer the feed's own <content:encoded> -- it's the clean
            # article body (no nav/sidebar/footer chrome) and comes for free
            # in the feed fetch we already made, so no extra HTTP round-trip.
            full_text, archive_path = _archive_and_extract_html(
                news_source.name, item.content_encoded.encode("utf-8")
            )
        else:
            # Not every WordPress feed configuration includes content:encoded
            # -- fall back to fetching the live article page.
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

    return _archive_and_extract_html(outlet_name, response.content)


def _archive_and_extract_html(outlet_name: str, html_bytes: bytes) -> tuple[str | None, str | None]:
    page_hash = sha256_hex(html_bytes)
    when = now_utc()
    directory = (
        Path(settings.archive_root) / "news" / slugify(outlet_name) / str(when.year) / when.strftime("%Y-%m-%d")
    )
    path = write_archive_file(directory, f"article_{page_hash[:12]}.html", html_bytes)

    try:
        parsed = parse_file(path, "text/html")
    except Exception:
        logger.info("news article text extraction failed for archived file %s", path)
        return None, str(path)

    return parsed.full_text, str(path)
