"""Seed the news-source registry with Ventura County local outlets whose
RSS feeds were verified live (see docs/superpowers/specs/
2026-08-01-ventura-news-feed-design.md). Safe to re-run — existing rows
are matched by rss_feed_url and left alone rather than duplicated.

Not every row here is a press outlet -- `authority_level` distinguishes
actual local-paper reporting ("media") from a political/issue org's own
blog or call-to-action feed ("advocacy"), so the dashboard/digest can flag
the latter rather than rendering it as if it were neutral coverage.
"""

from app.db import SessionLocal
from app.models import NewsSource

NEWS_SOURCES = [
    dict(
        name="Ventura Breeze",
        outlet_url="https://venturabreeze.com/",
        rss_feed_url="https://venturabreeze.com/feed/",
        connector="wordpress_rss",
        authority_level="media",
    ),
    dict(
        name="The Camarillo Acorn",
        outlet_url="https://www.thecamarilloacorn.com/",
        rss_feed_url="https://www.thecamarilloacorn.com/feed/",
        connector="wordpress_rss",
        authority_level="media",
    ),
    dict(
        name="The Acorn",
        outlet_url="https://www.theacorn.com/",
        rss_feed_url="https://www.theacorn.com/feed/",
        connector="wordpress_rss",
        authority_level="media",
    ),
    dict(
        name="Simi Valley Acorn",
        outlet_url="https://www.simivalleyacorn.com/",
        rss_feed_url="https://www.simivalleyacorn.com/feed/",
        connector="wordpress_rss",
        authority_level="media",
    ),
    dict(
        name="Moorpark Acorn",
        outlet_url="https://www.mpacorn.com/",
        rss_feed_url="https://www.mpacorn.com/feed/",
        connector="wordpress_rss",
        authority_level="media",
    ),
    dict(
        name="Thousand Oaks Acorn",
        outlet_url="https://www.toacorn.com/",
        rss_feed_url="https://www.toacorn.com/feed/",
        connector="wordpress_rss",
        authority_level="media",
    ),
    dict(
        name="Ventura County Star",
        outlet_url="https://www.vcstar.com/",
        rss_feed_url="https://news.google.com/rss/search?q=site%3Avcstar.com&hl=en-US&gl=US&ceid=US%3Aen",
        connector="google_news_proxy",
        authority_level="media",
    ),
    # These three outlets have no reachable first-party RSS: Fillmore Gazette's
    # site doesn't serve HTTPS at all, Santa Paula Times has no RSS feed
    # anywhere on its site (confirmed 404 on /feed/, no <link rel=alternate>),
    # and Ojai Valley News's /feed/ has failed with 404 then 429 across three
    # separate attempts. Same Google News proxy pattern as VC Star: snippet
    # only, connector code never follows the <link> (it's a Google redirect).
    dict(
        name="Fillmore Gazette",
        outlet_url="http://www.fillmoregazette.com/",
        rss_feed_url="https://news.google.com/rss/search?q=site%3Afillmoregazette.com&hl=en-US&gl=US&ceid=US%3Aen",
        connector="google_news_proxy",
        authority_level="media",
    ),
    dict(
        name="Santa Paula Times",
        outlet_url="https://santapaulatimes.com/",
        rss_feed_url="https://news.google.com/rss/search?q=site%3Asantapaulatimes.com&hl=en-US&gl=US&ceid=US%3Aen",
        connector="google_news_proxy",
        authority_level="media",
    ),
    dict(
        name="Ojai Valley News",
        outlet_url="https://www.ojaivalleynews.com/",
        rss_feed_url="https://news.google.com/rss/search?q=site%3Aojaivalleynews.com&hl=en-US&gl=US&ceid=US%3Aen",
        connector="google_news_proxy",
        authority_level="media",
    ),
    dict(
        name="Indivisible Ventura",
        outlet_url="https://indivisibleventura.org",
        rss_feed_url="https://indivisibleventura.org/feed/",
        connector="wordpress_rss",
        authority_level="advocacy",
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
