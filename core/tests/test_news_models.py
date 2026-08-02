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
