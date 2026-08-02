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
