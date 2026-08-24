import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Alert, Document, ManualSubmission, Source
from app.schemas import AlertOut, ReviewAction

router = APIRouter(prefix="/api", tags=["review"])


@router.get("/review-queue")
def review_queue(db: Session = Depends(get_db)):
    """Aggregates the flagged-item views from prd.md 9.13.5."""
    unreviewed_alerts = (
        db.query(Alert)
        .filter(Alert.reviewed.is_(False), Alert.alert_level >= 3)
        .order_by(Alert.alert_level.desc(), Alert.created_at.desc())
        .limit(100)
        .all()
    )
    parser_failures = (
        db.query(Document).filter(Document.parser_status == "failed").order_by(Document.created_at.desc()).limit(50).all()
    )
    vision_ocr_pending_review = (
        db.query(Document)
        .filter(Document.needs_human_review.is_(True))
        .order_by(Document.created_at.desc())
        .limit(50)
        .all()
    )
    source_failures = (
        db.query(Source).filter(Source.consecutive_failures >= 3).order_by(Source.consecutive_failures.desc()).all()
    )
    unverified_submissions = (
        db.query(ManualSubmission)
        .filter(ManualSubmission.verification_status == "unresolved")
        .order_by(ManualSubmission.submitted_at.desc())
        .limit(50)
        .all()
    )

    return {
        "high_priority_alerts": [AlertOut.model_validate(a).model_dump(mode="json") for a in unreviewed_alerts],
        "extraction_errors": [
            {"id": d.id, "title": d.title, "archive_path": d.archive_path, "parser_error": d.parser_error}
            for d in parser_failures
        ],
        "vision_ocr_pending_review": [
            {
                "id": d.id,
                "title": d.title,
                "archive_path": d.archive_path,
                "ocr_method": d.ocr_method,
                "note": "text extracted by vision-model OCR (handwritten/low-quality scan) -- verify against source image before trusting",
            }
            for d in vision_ocr_pending_review
        ],
        "source_failures": [
            {"id": s.id, "name": s.name, "consecutive_failures": s.consecutive_failures, "last_error": s.last_error}
            for s in source_failures
        ],
        "social_unverified": [
            {"id": m.id, "claimed_source": m.claimed_source, "content_text": m.content_text}
            for m in unverified_submissions
        ],
    }


@router.post("/review/{item_id}/approve", response_model=AlertOut)
def approve_alert(item_id: uuid.UUID, payload: ReviewAction, db: Session = Depends(get_db)):
    alert = db.get(Alert, item_id)
    if not alert:
        raise HTTPException(status_code=404, detail="alert not found")
    alert.reviewed = True
    alert.status = "approved"
    if payload.note:
        alert.operator_note = payload.note
    db.commit()
    db.refresh(alert)
    return alert


@router.post("/review/{item_id}/reject", response_model=AlertOut)
def reject_alert(item_id: uuid.UUID, payload: ReviewAction, db: Session = Depends(get_db)):
    alert = db.get(Alert, item_id)
    if not alert:
        raise HTTPException(status_code=404, detail="alert not found")
    alert.reviewed = True
    alert.status = "rejected"
    if payload.note:
        alert.operator_note = payload.note
    db.commit()
    db.refresh(alert)
    return alert
