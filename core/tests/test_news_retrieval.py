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

RSS_ONE_ITEM_WITH_CONTENT_ENCODED = b"""<?xml version="1.0"?>
<rss xmlns:content="http://purl.org/rss/1.0/modules/content/"><channel>
<item>
  <title>City Council Approves New Zoning Rules</title>
  <link>https://example.invalid/article-1</link>
  <description>The council voted on a zoning variance.</description>
  <content:encoded><![CDATA[<p>Full clean article body about zoning, no site chrome.</p>]]></content:encoded>
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


class TestWordpressRssContentEncoded:
    def test_uses_content_encoded_without_fetching_article_page(self, db, archive_root, monkeypatch):
        news_source = make_news_source(db, connector="wordpress_rss")
        calls = []

        def tracking_fetch(url, **kwargs):
            calls.append(url)
            return fake_response(RSS_ONE_ITEM_WITH_CONTENT_ENCODED)

        monkeypatch.setattr(retrieval_module, "fetch_url", tracking_fetch)

        poll_news_source(db, news_source)

        # Only the feed URL was fetched -- content:encoded made the article-page fetch unnecessary.
        assert calls == [news_source.rss_feed_url]
        article = db.query(NewsArticle).one()
        assert "Full clean article body about zoning, no site chrome." in article.full_text
        assert article.archive_path is not None

    def test_falls_back_to_page_fetch_when_content_encoded_absent(self, db, archive_root, monkeypatch):
        news_source = make_news_source(db, connector="wordpress_rss")
        calls = []

        def fetch_by_url(url, **kwargs):
            calls.append(url)
            if url == news_source.rss_feed_url:
                return fake_response(RSS_ONE_ITEM)
            return fake_response(b"<html><body><p>Full article body text.</p></body></html>")

        monkeypatch.setattr(retrieval_module, "fetch_url", fetch_by_url)

        poll_news_source(db, news_source)

        # No content:encoded in RSS_ONE_ITEM -- both the feed and the article page were fetched.
        assert calls == [news_source.rss_feed_url, "https://example.invalid/article-1"]
        article = db.query(NewsArticle).one()
        assert "Full article body text." in article.full_text


class TestPollNewsSourcePerItemIsolation:
    def test_one_bad_item_does_not_abort_the_whole_poll(self, db, archive_root, monkeypatch):
        news_source = make_news_source(db, connector="google_news_proxy")
        db.commit()  # the news_source row must survive the per-item rollback below, like a real
        # pre-existing source would -- db.rollback() rolls back the whole uncommitted
        # transaction, not just the failed item's work.
        monkeypatch.setattr(retrieval_module, "fetch_url", lambda url, **k: fake_response(RSS_TWO_ITEMS))

        original_archive_and_save = retrieval_module._archive_and_save
        calls = []

        def flaky_archive_and_save(db, news_source, item):
            calls.append(item.link)
            if len(calls) == 1:
                raise RuntimeError("simulated failure")
            return original_archive_and_save(db, news_source, item)

        monkeypatch.setattr(retrieval_module, "_archive_and_save", flaky_archive_and_save)

        created = poll_news_source(db, news_source)

        assert created == 1  # the second item still got created despite the first raising
        assert len(calls) == 2  # both items were attempted

    def test_caps_new_articles_per_poll(self, db, archive_root, monkeypatch):
        monkeypatch.setattr(retrieval_module, "MAX_NEW_ARTICLES_PER_POLL", 1)
        news_source = make_news_source(db, connector="google_news_proxy")
        monkeypatch.setattr(retrieval_module, "fetch_url", lambda url, **k: fake_response(RSS_TWO_ITEMS))

        created = poll_news_source(db, news_source)

        assert created == 1
