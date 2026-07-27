import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Alert
from app.schemas import AlertOut, AlertUpdate

router = APIRouter(prefix="/api/alerts", tags=["alerts"])


@router.get("", response_model=list[AlertOut])
def list_alerts(
    min_level: int = 1,
    reviewed: bool | None = None,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    query = db.query(Alert).filter(Alert.alert_level >= min_level)
    if reviewed is not None:
        query = query.filter(Alert.reviewed == reviewed)
    return query.order_by(Alert.alert_level.desc(), Alert.created_at.desc()).limit(min(limit, 500)).all()


@router.get("/{alert_id}", response_model=AlertOut)
def get_alert(alert_id: uuid.UUID, db: Session = Depends(get_db)):
    alert = db.get(Alert, alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail="alert not found")
    return alert


@router.patch("/{alert_id}", response_model=AlertOut)
def update_alert(alert_id: uuid.UUID, payload: AlertUpdate, db: Session = Depends(get_db)):
    alert = db.get(Alert, alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail="alert not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(alert, key, value)
    db.commit()
    db.refresh(alert)
    return alert
