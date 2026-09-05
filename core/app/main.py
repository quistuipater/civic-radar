import logging

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app import dashboard, models
from app.config import settings
from app.db import Base, SessionLocal, engine
from app.log_handler import DbLogHandler
from app.organization_tracker import dashboard as organization_tracker_dashboard
from app.organization_tracker import routers as organization_tracker
from app.routers import (
    alerts,
    app_settings,
    building_permits,
    crime_incidents,
    digest,
    documents,
    food_inspections,
    issues,
    logs,
    manual_submissions,
    meetings,
    news,
    review,
    search,
    sources,
)
from app.summaries import dashboard as summaries_dashboard

app = FastAPI(title=settings.project_name, version="0.1.0")

app.include_router(app_settings.router)
app.include_router(sources.router)
app.include_router(documents.router)
app.include_router(meetings.router)
app.include_router(issues.router)
app.include_router(alerts.router)
app.include_router(review.router)
app.include_router(search.router)
app.include_router(manual_submissions.router)
app.include_router(digest.router)
app.include_router(crime_incidents.router)
app.include_router(building_permits.router)
app.include_router(food_inspections.router)
app.include_router(logs.router)
app.include_router(news.router)
app.include_router(organization_tracker.router)
app.include_router(organization_tracker_dashboard.router)
app.include_router(summaries_dashboard.router)
app.include_router(dashboard.router)

app.mount("/archive", StaticFiles(directory=settings.archive_root), name="archive")


def _configure_error_logging() -> None:
    handler = DbLogHandler(SessionLocal)
    handler.setLevel(logging.ERROR)
    logging.getLogger().addHandler(handler)


def _ensure_app_settings_table() -> None:
    """New tables (like app_settings) aren't picked up by existing deployments
    until scripts/init_db.py is re-run by hand -- this repo has no migration
    tool. create_all only adds missing tables/is a no-op on ones that already
    exist, so it's safe to run unconditionally on every startup rather than
    rely on every operator remembering the manual step.
    """
    Base.metadata.create_all(bind=engine, tables=[models.AppSetting.__table__])


app.add_event_handler("startup", _configure_error_logging)
app.add_event_handler("startup", _ensure_app_settings_table)


@app.get("/healthz")
def healthz():
    return {"status": "ok"}
