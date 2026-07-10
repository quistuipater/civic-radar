import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- Sources ---


class SourceOut(ORMModel):
    id: uuid.UUID
    name: str
    jurisdiction: str | None
    agency: str | None
    body: str | None
    source_type: str
    authority_level: str
    url: str
    connector: str
    polling_interval_minutes: int | None
    enabled: bool
    reliability_score: int
    known_limitations: str | None
    last_fetched_at: datetime | None
    last_changed_at: datetime | None
    last_error: str | None
    consecutive_failures: int


class SourceCreate(BaseModel):
    name: str
    jurisdiction: str | None = None
    agency: str | None = None
    body: str | None = None
    source_type: str
    authority_level: str
    url: str
    connector: str = "generic"
    polling_interval_minutes: int = 240
    notes: str | None = None


class SourceUpdate(BaseModel):
    enabled: bool | None = None
    polling_interval_minutes: int | None = None
    notes: str | None = None
    reliability_score: int | None = None


# --- Documents ---


class DocumentOut(ORMModel):
    id: uuid.UUID
    source_id: uuid.UUID
    title: str | None
    document_type: str | None
    original_url: str | None
    archive_path: str
    mime_type: str | None
    file_size_bytes: int | None
    document_date: date | None
    meeting_date: date | None
    jurisdiction: str | None
    agency: str | None
    body: str | None
    project_number: str | None
    ordinance_number: str | None
    resolution_number: str | None
    parser_status: str
    parser_error: str | None
    created_at: datetime


# --- Meetings / Agenda Items ---


class AgendaItemOut(ORMModel):
    id: uuid.UUID
    meeting_id: uuid.UUID
    item_number: str | None
    title: str
    action_type: str | None
    consent_calendar: bool
    public_hearing: bool
    vote_expected: bool
    relevance_score: int | None
    urgency_score: int | None
    transparency_risk_score: int | None
    review_status: str


class MeetingOut(ORMModel):
    id: uuid.UUID
    jurisdiction: str
    agency: str
    body: str
    meeting_type: str | None
    start_time: datetime | None
    location: str | None
    status: str


# --- Issues ---


class IssueOut(ORMModel):
    id: uuid.UUID
    title: str
    slug: str
    summary: str | None
    jurisdiction: str | None
    status: str
    importance_score: int
    urgency_score: int
    controversy_score: int
    transparency_risk_score: int
    financial_impact_score: int
    legal_complexity_score: int
    next_deadline: datetime | None
    review_status: str
    publication_status: str
    created_at: datetime
    updated_at: datetime


class IssueCreate(BaseModel):
    title: str
    slug: str
    summary: str | None = None
    jurisdiction: str | None = None
    topic_categories: list[str] | None = None
    status: str = "new"


class IssueUpdate(BaseModel):
    title: str | None = None
    summary: str | None = None
    status: str | None = None
    review_status: str | None = None
    publication_status: str | None = None
    importance_score: int | None = None
    urgency_score: int | None = None
    controversy_score: int | None = None
    transparency_risk_score: int | None = None
    financial_impact_score: int | None = None
    legal_complexity_score: int | None = None
    next_deadline: datetime | None = None


class IssueLinkCreate(BaseModel):
    document_id: uuid.UUID | None = None
    agenda_item_id: uuid.UUID | None = None
    relationship_type: str = "manual"


# --- Alerts ---


class AlertOut(ORMModel):
    id: uuid.UUID
    issue_id: uuid.UUID | None
    document_id: uuid.UUID | None
    alert_level: int
    title: str
    summary: str | None
    trigger_reason: str | None
    deadline: datetime | None
    status: str
    reviewed: bool
    operator_note: str | None
    created_at: datetime


class AlertUpdate(BaseModel):
    status: str | None = None
    reviewed: bool | None = None


# --- Manual submissions ---


class ManualSubmissionCreate(BaseModel):
    submission_type: str
    source_description: str | None = None
    claimed_source: str | None = None
    content_text: str | None = None
    content_url: str | None = None
    related_issue_id: uuid.UUID | None = None
    operator_note: str | None = None


class ManualSubmissionOut(ORMModel):
    id: uuid.UUID
    submission_type: str
    source_description: str | None
    claimed_source: str | None
    content_text: str | None
    content_url: str | None
    verified: bool
    verification_status: str
    related_issue_id: uuid.UUID | None
    operator_note: str | None
    submitted_at: datetime


# --- Review queue ---


class ReviewAction(BaseModel):
    note: str | None = None
