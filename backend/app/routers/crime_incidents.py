import uuid
from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import CrimeIncident

router = APIRouter(prefix="/api", tags=["crime-incidents"])


@router.get("/crime-incidents")
def list_crime_incidents(
    offense_category: str | None = None,
    beat: str | None = None,
    community_council: str | None = None,
    since: datetime | None = None,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    query = db.query(CrimeIncident)
    if offense_category:
        query = query.filter(CrimeIncident.offense_category == offense_category)
    if beat:
        query = query.filter(CrimeIncident.beat == beat)
    if community_council:
        query = query.filter(CrimeIncident.community_council == community_council)
    if since:
        query = query.filter(CrimeIncident.incident_date_start >= since)
    rows = query.order_by(CrimeIncident.incident_date_start.desc()).limit(min(limit, 500)).all()
    return [
        {
            "id": r.id,
            "agency": r.agency,
            "report_number": r.report_number,
            "offense_category": r.offense_category,
            "offense_type": r.offense_type,
            "incident_date_start": r.incident_date_start,
            "incident_date_end": r.incident_date_end,
            "generalized_address": r.generalized_address,
            "council_district": r.council_district,
            "beat": r.beat,
            "community_council": r.community_council,
        }
        for r in rows
    ]


@router.get("/crime-incidents/{incident_id}")
def get_crime_incident(incident_id: uuid.UUID, db: Session = Depends(get_db)):
    incident = db.get(CrimeIncident, incident_id)
    if not incident:
        return {"error": "not found"}
    return {
        "id": incident.id,
        "agency": incident.agency,
        "report_number": incident.report_number,
        "offense_category": incident.offense_category,
        "offense_type": incident.offense_type,
        "incident_date_start": incident.incident_date_start,
        "incident_date_end": incident.incident_date_end,
        "generalized_address": incident.generalized_address,
        "council_district": incident.council_district,
        "beat": incident.beat,
        "community_council": incident.community_council,
        "raw_attributes": incident.raw_attributes,
    }
