import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.db import get_db
from app.export.markdown import render_issue_brief
from app.models import Issue, IssueLink
from app.schemas import IssueCreate, IssueLinkCreate, IssueOut, IssueUpdate

router = APIRouter(prefix="/api/issues", tags=["issues"])


@router.get("", response_model=list[IssueOut])
def list_issues(
    status: str | None = None,
    jurisdiction: str | None = None,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    query = db.query(Issue)
    if status:
        query = query.filter(Issue.status == status)
    if jurisdiction:
        query = query.filter(Issue.jurisdiction == jurisdiction)
    return query.order_by(Issue.updated_at.desc()).limit(min(limit, 500)).all()


@router.get("/{issue_id}", response_model=IssueOut)
def get_issue(issue_id: uuid.UUID, db: Session = Depends(get_db)):
    issue = db.get(Issue, issue_id)
    if not issue:
        raise HTTPException(status_code=404, detail="issue not found")
    return issue


@router.post("", response_model=IssueOut, status_code=201)
def create_issue(payload: IssueCreate, db: Session = Depends(get_db)):
    if db.query(Issue).filter(Issue.slug == payload.slug).one_or_none():
        raise HTTPException(status_code=409, detail="slug already in use")
    issue = Issue(**payload.model_dump())
    db.add(issue)
    db.commit()
    db.refresh(issue)
    return issue


@router.patch("/{issue_id}", response_model=IssueOut)
def update_issue(issue_id: uuid.UUID, payload: IssueUpdate, db: Session = Depends(get_db)):
    issue = db.get(Issue, issue_id)
    if not issue:
        raise HTTPException(status_code=404, detail="issue not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(issue, key, value)
    db.commit()
    db.refresh(issue)
    return issue


@router.post("/{issue_id}/links", status_code=201)
def attach_to_issue(issue_id: uuid.UUID, payload: IssueLinkCreate, db: Session = Depends(get_db)):
    issue = db.get(Issue, issue_id)
    if not issue:
        raise HTTPException(status_code=404, detail="issue not found")
    if not payload.document_id and not payload.agenda_item_id:
        raise HTTPException(status_code=422, detail="must provide document_id or agenda_item_id")
    link = IssueLink(
        issue_id=issue_id,
        document_id=payload.document_id,
        agenda_item_id=payload.agenda_item_id,
        relationship_type=payload.relationship_type,
        confidence="operator",
        created_by="operator",
    )
    db.add(link)
    db.commit()
    return {"id": link.id}


@router.get("/{issue_id}/brief.md", response_class=PlainTextResponse)
def get_issue_brief(issue_id: uuid.UUID, db: Session = Depends(get_db)):
    issue = db.get(Issue, issue_id)
    if not issue:
        raise HTTPException(status_code=404, detail="issue not found")
    return render_issue_brief(db, issue)
