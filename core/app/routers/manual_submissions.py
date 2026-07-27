import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import ManualSubmission
from app.schemas import ManualSubmissionCreate, ManualSubmissionOut

router = APIRouter(prefix="/api/manual-submissions", tags=["manual-submissions"])


@router.get("", response_model=list[ManualSubmissionOut])
def list_manual_submissions(limit: int = 100, db: Session = Depends(get_db)):
    return db.query(ManualSubmission).order_by(ManualSubmission.submitted_at.desc()).limit(min(limit, 500)).all()


@router.post("", response_model=ManualSubmissionOut, status_code=201)
def create_manual_submission(payload: ManualSubmissionCreate, db: Session = Depends(get_db)):
    """Stores a manually submitted item as unverified (prd.md 13.3, 15.4). Social/
    community claims never start out verified — confirmation against an official
    source is a separate, human-driven step."""
    submission = ManualSubmission(**payload.model_dump(), verified=False, verification_status="unresolved")
    db.add(submission)
    db.commit()
    db.refresh(submission)
    return submission


@router.patch("/{submission_id}", response_model=ManualSubmissionOut)
def update_manual_submission(
    submission_id: uuid.UUID,
    verification_status: str | None = None,
    operator_note: str | None = None,
    db: Session = Depends(get_db),
):
    submission = db.get(ManualSubmission, submission_id)
    if not submission:
        raise HTTPException(status_code=404, detail="manual submission not found")
    if verification_status:
        submission.verification_status = verification_status
        submission.verified = verification_status == "confirmed"
    if operator_note is not None:
        submission.operator_note = operator_note
    db.commit()
    db.refresh(submission)
    return submission
