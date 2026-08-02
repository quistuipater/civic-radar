"""Tests for /api/news -- topic/outlet filtering and before-cursor
pagination, mirroring test_router_logs.py's conventions.
"""

from datetime import timedelta
from urllib.parse import quote

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

        resp = client.get(f"/api/news?before={quote(now.isoformat())}")

        body = resp.json()
        assert len(body) == 1
        assert body[0]["title"] == "Older"

    def test_malformed_source_id_returns_400_not_500(self, client, db):
        resp = client.get("/api/news?source_id=not-a-uuid")

        assert resp.status_code == 400

    def test_malformed_before_returns_400_not_500(self, client, db):
        resp = client.get("/api/news?before=not-a-date")

        assert resp.status_code == 400
