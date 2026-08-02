"""Seed the news-source registry with Ventura County local outlets whose
RSS feeds were verified live (see docs/superpowers/specs/
2026-08-01-ventura-news-feed-design.md). Safe to re-run — existing rows
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
