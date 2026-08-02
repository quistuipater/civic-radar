"""Smoke tests: every page/endpoint should at least render without a 500,
including against a completely empty database. These don't assert much
about content -- their job is to catch "the template crashes because a
list is empty" or "a route references a column that no longer exists"
before a human notices in the browser.
"""

from .conftest import make_news_source, make_source


class TestDashboardPages:
    def test_home_page_renders_with_empty_database(self, client):
        resp = client.get("/")
        assert resp.status_code == 200

    def test_home_page_renders_with_data(self, client, db):
        make_source(db, name="A Source")
        db.commit()
        resp = client.get("/")
        assert resp.status_code == 200
        assert "A Source" not in resp.text  # home page lists documents/alerts, not sources directly

    def test_sources_page_renders(self, client, db):
        make_source(db, name="Test Registry Source")
        db.commit()
        resp = client.get("/sources")
        assert resp.status_code == 200
        assert "Test Registry Source" in resp.text

    def test_sources_page_renders_with_no_fetches_yet(self, client, db):
        make_source(db)
        db.commit()
        resp = client.get("/sources")
        assert resp.status_code == 200
        assert "no fetches yet" in resp.text

    def test_digest_page_renders_with_empty_database(self, client):
        resp = client.get("/digest")
        assert resp.status_code == 200

    def test_digest_markdown_export_renders(self, client):
        resp = client.get("/api/digest/daily.md")
        assert resp.status_code == 200

    def test_logs_page_renders_with_empty_database(self, client):
        resp = client.get("/logs")
        assert resp.status_code == 200

    def test_logs_page_renders_with_sources(self, client, db):
        make_source(db, name="A Logs Source")
        db.commit()
        resp = client.get("/logs")
        assert resp.status_code == 200
        assert "A Logs Source" in resp.text

    def test_news_page_renders_with_empty_database(self, client):
        resp = client.get("/news")

        assert resp.status_code == 200

    def test_news_page_renders_with_news_sources(self, client, db):
        make_news_source(db, name="Ventura Breeze")
        db.commit()

        resp = client.get("/news")

        assert resp.status_code == 200
        assert "Ventura Breeze" in resp.text


class TestHealthAndApi:
    def test_healthz(self, client):
        resp = client.get("/healthz")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    def test_crime_incidents_api_empty(self, client):
        resp = client.get("/api/crime-incidents")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_logs_api_empty(self, client):
        resp = client.get("/api/logs")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_news_api_empty(self, client):
        resp = client.get("/api/news")

        assert resp.status_code == 200
        assert resp.json() == []
