from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.db import get_db
from app.export.digest import DEFAULT_WINDOW_HOURS, build_daily_digest, render_digest_markdown

router = APIRouter(prefix="/api", tags=["digest"])


@router.get("/digest/daily.md", response_class=PlainTextResponse)
def get_daily_digest_markdown(window_hours: int = DEFAULT_WINDOW_HOURS, db: Session = Depends(get_db)):
    digest = build_daily_digest(db, window_hours=window_hours)
    return render_digest_markdown(digest)
