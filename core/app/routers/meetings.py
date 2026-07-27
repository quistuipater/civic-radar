import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import AgendaItem, Meeting
from app.schemas import AgendaItemOut, MeetingOut

router = APIRouter(prefix="/api", tags=["meetings"])


@router.get("/meetings", response_model=list[MeetingOut])
def list_meetings(
    jurisdiction: str | None = None,
    body: str | None = None,
    upcoming_only: bool = False,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    query = db.query(Meeting)
    if jurisdiction:
        query = query.filter(Meeting.jurisdiction == jurisdiction)
    if body:
        query = query.filter(Meeting.body == body)
    if upcoming_only:
        query = query.filter(Meeting.status == "scheduled")
    return query.order_by(Meeting.start_time.desc()).limit(min(limit, 500)).all()


@router.get("/meetings/{meeting_id}", response_model=MeetingOut)
def get_meeting(meeting_id: uuid.UUID, db: Session = Depends(get_db)):
    meeting = db.get(Meeting, meeting_id)
    if not meeting:
        raise HTTPException(status_code=404, detail="meeting not found")
    return meeting


@router.get("/agenda-items", response_model=list[AgendaItemOut])
def list_agenda_items(meeting_id: uuid.UUID | None = None, limit: int = 100, db: Session = Depends(get_db)):
    query = db.query(AgendaItem)
    if meeting_id:
        query = query.filter(AgendaItem.meeting_id == meeting_id)
    return query.order_by(AgendaItem.created_at.desc()).limit(min(limit, 500)).all()


@router.get("/agenda-items/{agenda_item_id}", response_model=AgendaItemOut)
def get_agenda_item(agenda_item_id: uuid.UUID, db: Session = Depends(get_db)):
    item = db.get(AgendaItem, agenda_item_id)
    if not item:
        raise HTTPException(status_code=404, detail="agenda item not found")
    return item
