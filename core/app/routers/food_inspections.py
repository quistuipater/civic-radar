import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import FoodInspection

router = APIRouter(prefix="/api", tags=["food-inspections"])


@router.get("/food-inspections")
def list_food_inspections(
    business_name: str | None = None,
    violation_status: str | None = None,
    address: str | None = None,
    since: datetime | None = None,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    query = db.query(FoodInspection)
    if business_name:
        query = query.filter(FoodInspection.business_name.ilike(f"%{business_name}%"))
    if violation_status:
        query = query.filter(FoodInspection.violation_status == violation_status)
    if address:
        query = query.filter(FoodInspection.address.ilike(f"%{address}%"))
    if since:
        query = query.filter(FoodInspection.violation_date >= since)
    rows = query.order_by(FoodInspection.violation_date.desc()).limit(min(limit, 500)).all()
    return [
        {
            "id": r.id,
            "external_id": r.external_id,
            "business_name": r.business_name,
            "license_number": r.license_number,
            "result": r.result,
            "violation_code": r.violation_code,
            "violation_level": r.violation_level,
            "violation_description": r.violation_description,
            "violation_status": r.violation_status,
            "comments": r.comments,
            "address": r.address,
            "violation_date": r.violation_date,
        }
        for r in rows
    ]


@router.get("/food-inspections/{inspection_id}")
def get_food_inspection(inspection_id: uuid.UUID, db: Session = Depends(get_db)):
    inspection = db.get(FoodInspection, inspection_id)
    if not inspection:
        raise HTTPException(status_code=404, detail="food inspection not found")
    return {
        "id": inspection.id,
        "external_id": inspection.external_id,
        "business_name": inspection.business_name,
        "license_number": inspection.license_number,
        "result": inspection.result,
        "violation_code": inspection.violation_code,
        "violation_level": inspection.violation_level,
        "violation_description": inspection.violation_description,
        "violation_status": inspection.violation_status,
        "comments": inspection.comments,
        "address": inspection.address,
        "violation_date": inspection.violation_date,
        "raw_attributes": inspection.raw_attributes,
    }
