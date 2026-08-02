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
