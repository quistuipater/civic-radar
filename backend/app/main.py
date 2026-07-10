from fastapi import FastAPI

from app import dashboard
from app.routers import (
    alerts,
    crime_incidents,
    digest,
    documents,
    issues,
    manual_submissions,
    meetings,
    review,
    search,
    sources,
)

app = FastAPI(title="Santa Cruz Civic Radar", version="0.1.0")

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
app.include_router(dashboard.router)


@app.get("/healthz")
def healthz():
    return {"status": "ok"}
