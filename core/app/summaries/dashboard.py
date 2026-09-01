"""Server-rendered dashboard pages for narrative summaries -- the "filed in
the dashboard" side of daily/weekly recaps (see worker.run_summary_batch
for generation/emailing). Shares the same Jinja2Templates instance as the
rest of the dashboard (app/dashboard.py, organization_tracker/dashboard.py).
"""

import uuid

from fastapi import APIRouter, Depends, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import NarrativeSummary
from app.summaries.formatting import highlight_figures

router = APIRouter(tags=["summaries-dashboard"])
templates = Jinja2Templates(directory="app/templates")
templates.env.globals["project_name"] = settings.project_name
templates.env.filters["highlight_figures"] = highlight_figures

SUMMARIES_PAGE_SIZE = 30


@router.get("/summaries")
def summaries_list_page(request: Request, period_type: str = "", db: Session = Depends(get_db)):
    query = db.query(NarrativeSummary)
    if period_type in ("daily", "weekly"):
        query = query.filter(NarrativeSummary.period_type == period_type)
    summaries = query.order_by(NarrativeSummary.period_start.desc()).limit(SUMMARIES_PAGE_SIZE).all()
    return templates.TemplateResponse(
        "summaries_list.html",
        {"request": request, "summaries": summaries, "period_type": period_type},
    )


@router.get("/summaries/{summary_id}")
def summary_detail_page(summary_id: uuid.UUID, request: Request, db: Session = Depends(get_db)):
    summary = db.get(NarrativeSummary, summary_id)
    stats = summary.stats_json if summary else None
    return templates.TemplateResponse(
        "summary_detail.html", {"request": request, "summary": summary, "stats": stats, "theme": "dark"}
    )
