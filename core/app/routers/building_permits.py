import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import BuildingPermit

router = APIRouter(prefix="/api", tags=["building-permits"])


@router.get("/building-permits")
def list_building_permits(
    status: str | None = None,
    ward: str | None = None,
    address: str | None = None,
    since: datetime | None = None,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    query = db.query(BuildingPermit)
    if status:
        query = query.filter(BuildingPermit.status == status)
    if ward:
        query = query.filter(BuildingPermit.ward == ward)
    if address:
        query = query.filter(BuildingPermit.address.ilike(f"%{address}%"))
    if since:
        query = query.filter(BuildingPermit.issued_date >= since)
    rows = query.order_by(BuildingPermit.issued_date.desc()).limit(min(limit, 500)).all()
    return [
        {
            "id": r.id,
            "external_id": r.external_id,
            "permit_type": r.permit_type,
            "work_type": r.work_type,
            "description": r.description,
            "applicant": r.applicant,
            "declared_valuation": r.declared_valuation,
            "status": r.status,
            "address": r.address,
            "ward": r.ward,
            "issued_date": r.issued_date,
            "expiration_date": r.expiration_date,
        }
        for r in rows
    ]


@router.get("/building-permits/{permit_id}")
def get_building_permit(permit_id: uuid.UUID, db: Session = Depends(get_db)):
    permit = db.get(BuildingPermit, permit_id)
    if not permit:
        raise HTTPException(status_code=404, detail="building permit not found")
    return {
        "id": permit.id,
        "external_id": permit.external_id,
        "permit_type": permit.permit_type,
        "work_type": permit.work_type,
        "description": permit.description,
        "applicant": permit.applicant,
        "declared_valuation": permit.declared_valuation,
        "status": permit.status,
        "address": permit.address,
        "ward": permit.ward,
        "issued_date": permit.issued_date,
        "expiration_date": permit.expiration_date,
        "raw_attributes": permit.raw_attributes,
    }
