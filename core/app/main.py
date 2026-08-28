import logging

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app import dashboard, record_provenance
from app.config import settings
from app.db import SessionLocal
from app.log_handler import DbLogHandler
from app.organization_tracker import dashboard as organization_tracker_dashboard
from app.organization_tracker import routers as organization_tracker
from app.routers import (
    alerts,
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

app = FastAPI(title=settings.project_name, version="0.1.0")

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
app.include_router(dashboard.router)

app.mount("/archive", StaticFiles(directory=settings.archive_root), name="archive")


def _configure_error_logging() -> None:
    handler = DbLogHandler(SessionLocal)
    handler.setLevel(logging.ERROR)
    logging.getLogger().addHandler(handler)


app.add_event_handler("startup", _configure_error_logging)


@app.get("/healthz")
def healthz():
    return {"status": "ok"}
