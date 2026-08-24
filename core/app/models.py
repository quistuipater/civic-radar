import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    ARRAY,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def uuid_pk():
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class Source(Base):
    """A monitored source: an agenda center, notice page, filing portal, etc. (prd.md 9.1)."""

    __tablename__ = "sources"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(Text, nullable=False)
    jurisdiction: Mapped[str | None] = mapped_column(Text)
    agency: Mapped[str | None] = mapped_column(Text)
    body: Mapped[str | None] = mapped_column(Text)
    source_type: Mapped[str] = mapped_column(Text, nullable=False)
    authority_level: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    fetch_method: Mapped[str] = mapped_column(Text, nullable=False, default="html_pdf_harvest")
    connector: Mapped[str] = mapped_column(Text, nullable=False, default="generic")
    polling_interval_minutes: Mapped[int | None] = mapped_column(Integer, default=240)
    parser_type: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    reliability_score: Mapped[int] = mapped_column(Integer, default=5)
    known_limitations: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    last_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    fetches: Mapped[list["Fetch"]] = relationship(back_populates="source")
    documents: Mapped[list["Document"]] = relationship(back_populates="source")


class Fetch(Base):
    """One polling attempt against a source (prd.md 9.2)."""

    __tablename__ = "fetches"

    id: Mapped[uuid.UUID] = uuid_pk()
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sources.id"))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    status: Mapped[str] = mapped_column(Text, nullable=False)
    http_status: Mapped[int | None] = mapped_column(Integer)
    content_hash: Mapped[str | None] = mapped_column(Text)
    archive_path: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    changed: Mapped[bool] = mapped_column(Boolean, default=False)
    # Connector health, distinct from `status`/`http_status` (which only say
    # the HTTP request succeeded): items_found is how many
    # documents/links/features the connector actually discovered in the
    # response, and validation_status/message flag when a *successful* fetch
    # still looks wrong -- e.g. a page that normally has ~200 links coming
    # back with 0 (site structure changed under us), or an ArcGIS layer
    # missing an expected field. "ok" HTTP status alone doesn't catch either.
    items_found: Mapped[int | None] = mapped_column(Integer)
    validation_status: Mapped[str | None] = mapped_column(Text)
    validation_message: Mapped[str | None] = mapped_column(Text)

    source: Mapped["Source"] = relationship(back_populates="fetches")


class Document(Base):
    """An archived, hashed artifact — agenda, staff report, notice, etc. (prd.md 9.3-9.4)."""

    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = uuid_pk()
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sources.id"))
    fetch_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("fetches.id"))
    title: Mapped[str | None] = mapped_column(Text)
    document_type: Mapped[str | None] = mapped_column(Text)
    original_url: Mapped[str | None] = mapped_column(Text)
    archive_path: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(Text, nullable=False)
    mime_type: Mapped[str | None] = mapped_column(Text)
    file_size_bytes: Mapped[int | None] = mapped_column(Integer)
    document_date: Mapped[datetime | None] = mapped_column(Date)
    meeting_date: Mapped[datetime | None] = mapped_column(Date)
    jurisdiction: Mapped[str | None] = mapped_column(Text)
    agency: Mapped[str | None] = mapped_column(Text)
    body: Mapped[str | None] = mapped_column(Text)
    project_number: Mapped[str | None] = mapped_column(Text)
    ordinance_number: Mapped[str | None] = mapped_column(Text)
    resolution_number: Mapped[str | None] = mapped_column(Text)
    applicant: Mapped[str | None] = mapped_column(Text)
    address: Mapped[str | None] = mapped_column(Text)
    apn: Mapped[str | None] = mapped_column(Text)
    public_hearing_date: Mapped[datetime | None] = mapped_column(Date)
    comment_deadline: Mapped[datetime | None] = mapped_column(Date)
    parser_status: Mapped[str] = mapped_column(Text, default="pending")
    parser_error: Mapped[str | None] = mapped_column(Text)
    extracted_text_path: Mapped[str | None] = mapped_column(Text)
    # Set by parse_document() when any page's text came from the vision-OCR
    # fallback (app/parsing/extract.py) rather than embedded PDF text or
    # Tesseract. needs_human_review defaults true in that case -- confirmed
    # live 2026-08-18 that vision-OCR'd text can be fluently, confidently
    # wrong (a handwritten name misread as a different, equally plausible
    # real name), which is worse to silently trust than Tesseract's
    # obviously-garbled output ever was. Cleared via PATCH /api/documents/
    # {id} once a human has checked it against the source image.
    ocr_method: Mapped[str | None] = mapped_column(Text)
    needs_human_review: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (UniqueConstraint("source_id", "content_hash", name="uq_document_source_hash"),)

    source: Mapped["Source"] = relationship(back_populates="documents")
    chunks: Mapped[list["DocumentChunk"]] = relationship(back_populates="document", cascade="all, delete-orphan")


class DocumentChunk(Base):
    """Page/section-level chunk of a document, with an embedding for semantic search (prd.md 9.10, 10.1)."""

    __tablename__ = "document_chunks"

    id: Mapped[uuid.UUID] = uuid_pk()
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id"))
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    page_start: Mapped[int | None] = mapped_column(Integer)
    page_end: Mapped[int | None] = mapped_column(Integer)
    section_title: Mapped[str | None] = mapped_column(Text)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int | None] = mapped_column(Integer)
    embedding = mapped_column(Vector(768), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    document: Mapped["Document"] = relationship(back_populates="chunks")


class Meeting(Base):
    """A public meeting of a body (prd.md 9.5)."""

    __tablename__ = "meetings"

    id: Mapped[uuid.UUID] = uuid_pk()
    jurisdiction: Mapped[str] = mapped_column(Text, nullable=False)
    agency: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    meeting_type: Mapped[str | None] = mapped_column(Text)
    start_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    location: Mapped[str | None] = mapped_column(Text)
    remote_url: Mapped[str | None] = mapped_column(Text)
    agenda_document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("documents.id"))
    packet_document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("documents.id"))
    minutes_document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("documents.id"))
    video_url: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="scheduled")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("jurisdiction", "body", "start_time", name="uq_meeting_body_start"),
    )

    agenda_items: Mapped[list["AgendaItem"]] = relationship(back_populates="meeting")


class MeetingTranscript(Base):
    """A WhisperX-transcribed, speaker-diarized meeting audio recording.
    Not in prd.md's schema -- audio/diarized-segment data doesn't fit the
    Document model any more than CrimeIncident's structured rows did, same
    reasoning there (see app/ingestion/crime_data.py). Segments are stored
    as one JSONB blob rather than one row per segment: there's no query
    pattern here that needs filtering by individual segment, only "give me
    this meeting's whole transcript" -- see app/ai/meeting_audio.py.
    """

    __tablename__ = "meeting_transcripts"

    id: Mapped[uuid.UUID] = uuid_pk()
    # Nullable: matching an audio item back to a Meeting row is a best-effort
    # date/body match against free-text RSS titles (see
    # app/ingestion/meeting_audio.py) -- a failed match shouldn't mean
    # dropping an otherwise-good transcript.
    meeting_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("meetings.id"))
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sources.id"))
    title: Mapped[str | None] = mapped_column(Text)
    archive_path: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(Text, nullable=False)
    original_url: Mapped[str | None] = mapped_column(Text)
    duration_seconds: Mapped[float | None] = mapped_column(Float)
    language: Mapped[str | None] = mapped_column(Text)
    speaker_count: Mapped[int | None] = mapped_column(Integer)
    segments: Mapped[list | None] = mapped_column(JSONB)
    model_name: Mapped[str] = mapped_column(Text, nullable=False)
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (UniqueConstraint("source_id", "content_hash", name="uq_meeting_transcript_source_hash"),)


class AgendaItem(Base):
    """A single item on a meeting agenda (prd.md 9.5)."""

    __tablename__ = "agenda_items"

    id: Mapped[uuid.UUID] = uuid_pk()
    meeting_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("meetings.id"))
    item_number: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    department: Mapped[str | None] = mapped_column(Text)
    staff_recommendation: Mapped[str | None] = mapped_column(Text)
    action_type: Mapped[str | None] = mapped_column(Text)
    consent_calendar: Mapped[bool] = mapped_column(Boolean, default=False)
    public_hearing: Mapped[bool] = mapped_column(Boolean, default=False)
    vote_expected: Mapped[bool] = mapped_column(Boolean, default=False)
    relevance_score: Mapped[int | None] = mapped_column(Integer)
    urgency_score: Mapped[int | None] = mapped_column(Integer)
    transparency_risk_score: Mapped[int | None] = mapped_column(Integer)
    ai_summary: Mapped[str | None] = mapped_column(Text)
    human_summary: Mapped[str | None] = mapped_column(Text)
    review_status: Mapped[str] = mapped_column(Text, default="unreviewed")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    meeting: Mapped["Meeting"] = relationship(back_populates="agenda_items")


class Issue(Base):
    """The central product object: a civic matter tracked over time (prd.md 9.6)."""

    __tablename__ = "issues"

    id: Mapped[uuid.UUID] = uuid_pk()
    title: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    jurisdiction: Mapped[str | None] = mapped_column(Text)
    agencies_involved: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    topic_categories: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    geography: Mapped[str | None] = mapped_column(Text)
    districts_affected: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    status: Mapped[str] = mapped_column(Text, default="new")
    importance_score: Mapped[int] = mapped_column(Integer, default=0)
    urgency_score: Mapped[int] = mapped_column(Integer, default=0)
    controversy_score: Mapped[int] = mapped_column(Integer, default=0)
    transparency_risk_score: Mapped[int] = mapped_column(Integer, default=0)
    financial_impact_score: Mapped[int] = mapped_column(Integer, default=0)
    legal_complexity_score: Mapped[int] = mapped_column(Integer, default=0)
    first_detected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_meeting_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("meetings.id"))
    decision_makers: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    known_supporters: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    known_opponents: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    source_confidence: Mapped[str | None] = mapped_column(Text)
    review_status: Mapped[str] = mapped_column(Text, default="unreviewed")
    publication_status: Mapped[str] = mapped_column(Text, default="internal")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    events: Mapped[list["IssueEvent"]] = relationship(back_populates="issue", order_by="IssueEvent.event_date")
    links: Mapped[list["IssueLink"]] = relationship(back_populates="issue")


class IssueEvent(Base):
    """A dated occurrence on an issue's timeline (prd.md 9.7)."""

    __tablename__ = "issue_events"

    id: Mapped[uuid.UUID] = uuid_pk()
    issue_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("issues.id"))
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    event_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("documents.id"))
    agenda_item_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agenda_items.id"))
    source_authority: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[str | None] = mapped_column(Text)
    reviewed: Mapped[bool] = mapped_column(Boolean, default=False)
    public_visibility: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    issue: Mapped["Issue"] = relationship(back_populates="events")


class IssueLink(Base):
    """Attaches a document/agenda item to an issue (prd.md 9.6, 9.11)."""

    __tablename__ = "issue_links"

    id: Mapped[uuid.UUID] = uuid_pk()
    issue_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("issues.id"))
    document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("documents.id"))
    agenda_item_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agenda_items.id"))
    relationship_type: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(Text, default="system")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    issue: Mapped["Issue"] = relationship(back_populates="links")


class Entity(Base):
    """A canonical person/org/agency referenced across documents (prd.md 9.10)."""

    __tablename__ = "entities"

    id: Mapped[uuid.UUID] = uuid_pk()
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)
    canonical_name: Mapped[str] = mapped_column(Text, nullable=False)
    aliases: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class EntityMention(Base):
    """One occurrence of an entity in a document/agenda item/issue (prd.md 9.10)."""

    __tablename__ = "entity_mentions"

    id: Mapped[uuid.UUID] = uuid_pk()
    entity_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("entities.id"))
    document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("documents.id"))
    agenda_item_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agenda_items.id"))
    issue_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("issues.id"))
    mention_text: Mapped[str | None] = mapped_column(Text)
    page_number: Mapped[int | None] = mapped_column(Integer)
    confidence: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Alert(Base):
    """A generated alert at level 1 (Captured) through 4 (High Impact/Imminent) (prd.md 9.12)."""

    __tablename__ = "alerts"

    id: Mapped[uuid.UUID] = uuid_pk()
    issue_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("issues.id"))
    agenda_item_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agenda_items.id"))
    document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("documents.id"))
    alert_level: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    trigger_reason: Mapped[str | None] = mapped_column(Text)
    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dedup_key: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="new")
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewed: Mapped[bool] = mapped_column(Boolean, default=False)
    operator_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (UniqueConstraint("dedup_key", name="uq_alert_dedup_key"),)


class Prompt(Base):
    """A versioned prompt template used by the AI layer (prd.md 10.3)."""

    __tablename__ = "prompts"

    id: Mapped[uuid.UUID] = uuid_pk()
    prompt_key: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_version: Mapped[str] = mapped_column(Text, nullable=False)
    task_type: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_text: Mapped[str] = mapped_column(Text, nullable=False)
    model_name: Mapped[str | None] = mapped_column(Text)
    model_params: Mapped[dict | None] = mapped_column(JSONB)
    json_schema: Mapped[dict | None] = mapped_column(JSONB)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (UniqueConstraint("prompt_key", "prompt_version", name="uq_prompt_key_version"),)


class AiOutput(Base):
    """A single AI job's output, traceable to prompt version and model (prd.md 10.3, 11.1)."""

    __tablename__ = "ai_outputs"

    id: Mapped[uuid.UUID] = uuid_pk()
    task_type: Mapped[str] = mapped_column(Text, nullable=False)
    model_name: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_version: Mapped[str] = mapped_column(Text, nullable=False)
    input_ref_type: Mapped[str] = mapped_column(Text, nullable=False)
    input_ref_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    output_json: Mapped[dict | None] = mapped_column(JSONB)
    output_text: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    reviewed: Mapped[bool] = mapped_column(Boolean, default=False)
    operator_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ManualSubmission(Base):
    """A manually submitted item — pasted text, screenshot, URL, etc. (prd.md 13.3)."""

    __tablename__ = "manual_submissions"

    id: Mapped[uuid.UUID] = uuid_pk()
    submission_type: Mapped[str] = mapped_column(Text, nullable=False)
    source_description: Mapped[str | None] = mapped_column(Text)
    claimed_source: Mapped[str | None] = mapped_column(Text)
    content_text: Mapped[str | None] = mapped_column(Text)
    content_url: Mapped[str | None] = mapped_column(Text)
    file_archive_path: Mapped[str | None] = mapped_column(Text)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    verification_status: Mapped[str] = mapped_column(Text, default="unresolved")
    related_issue_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("issues.id"))
    operator_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CrimeIncident(Base):
    """A single incident/offense record from a law-enforcement open-data feed
    (e.g. an ArcGIS FeatureServer) -- structurally different from Document:
    there's no PDF/HTML to archive-then-parse, just a structured row per
    incident, so it gets its own table rather than being forced through the
    Document pipeline. raw_attributes preserves the full source record
    (archive-first, applied at the row level) alongside the normalized
    fields used for querying/display.
    """

    __tablename__ = "crime_incidents"

    id: Mapped[uuid.UUID] = uuid_pk()
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sources.id"))
    agency: Mapped[str] = mapped_column(Text, nullable=False)
    external_id: Mapped[str] = mapped_column(Text, nullable=False)
    report_number: Mapped[str | None] = mapped_column(Text)
    offense_category: Mapped[str | None] = mapped_column(Text)
    offense_type: Mapped[str | None] = mapped_column(Text)
    incident_date_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    incident_date_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    generalized_address: Mapped[str | None] = mapped_column(Text)
    council_district: Mapped[str | None] = mapped_column(Text)
    beat: Mapped[str | None] = mapped_column(Text)
    community_council: Mapped[str | None] = mapped_column(Text)
    raw_attributes: Mapped[dict | None] = mapped_column(JSONB)
    # The source system's own "record created" timestamp (distinct from
    # incident_date_start, which is when the crime happened) -- used as the
    # incremental-sync cursor, since these datasets (tens of thousands of
    # rows) are too large to re-fetch in full on every poll.
    source_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (UniqueConstraint("source_id", "external_id", name="uq_crime_incident_source_external"),)


class BuildingPermit(Base):
    """A single permit record from a municipal open-data CKAN feed (e.g.
    Analyze Boston's Approved Building Permits dataset) -- same rationale as
    CrimeIncident: a structured row per permit, no PDF/HTML to archive-then-
    parse, so it gets its own table rather than the Document pipeline.
    """

    __tablename__ = "building_permits"

    id: Mapped[uuid.UUID] = uuid_pk()
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sources.id"))
    external_id: Mapped[str] = mapped_column(Text, nullable=False)
    permit_type: Mapped[str | None] = mapped_column(Text)
    work_type: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    applicant: Mapped[str | None] = mapped_column(Text)
    declared_valuation: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str | None] = mapped_column(Text)
    address: Mapped[str | None] = mapped_column(Text)
    ward: Mapped[str | None] = mapped_column(Text)
    issued_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expiration_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    raw_attributes: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (UniqueConstraint("source_id", "external_id", name="uq_building_permit_source_external"),)


class FoodInspection(Base):
    """A single inspection/violation line item from a municipal health-code
    open-data CKAN feed (e.g. Analyze Boston's Food Establishment
    Inspections dataset). One row per violation cited during an inspection
    visit -- there is no separate "violations" dataset upstream, the
    inspections feed already carries violation code/description/status per
    row (see core/app/ingestion/food_inspections.py docstring).
    """

    __tablename__ = "food_inspections"

    id: Mapped[uuid.UUID] = uuid_pk()
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sources.id"))
    external_id: Mapped[str] = mapped_column(Text, nullable=False)
    business_name: Mapped[str | None] = mapped_column(Text)
    license_number: Mapped[str | None] = mapped_column(Text)
    result: Mapped[str | None] = mapped_column(Text)
    violation_code: Mapped[str | None] = mapped_column(Text)
    violation_level: Mapped[str | None] = mapped_column(Text)
    violation_description: Mapped[str | None] = mapped_column(Text)
    violation_status: Mapped[str | None] = mapped_column(Text)
    comments: Mapped[str | None] = mapped_column(Text)
    address: Mapped[str | None] = mapped_column(Text)
    violation_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    raw_attributes: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (UniqueConstraint("source_id", "external_id", name="uq_food_inspection_source_external"),)


class AppLog(Base):
    """A captured ERROR+ log record, written by DbLogHandler (see
    app/log_handler.py) from every logger in the process. Exists so
    application errors (worker crashes, unhandled exceptions) are visible
    in the dashboard's Logs tab instead of only in Docker/stdout logs.
    """

    __tablename__ = "app_logs"

    id: Mapped[uuid.UUID] = uuid_pk()
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    level: Mapped[str] = mapped_column(Text, nullable=False)
    logger_name: Mapped[str] = mapped_column(Text, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    traceback: Mapped[str | None] = mapped_column(Text)
    source_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("sources.id"), nullable=True)


class NewsSource(Base):
    """A monitored local news outlet's RSS feed. Wholly independent of
    Source/Fetch/Document -- news coverage is context, not a reviewable
    civic record, and this table intentionally carries none of the
    gov-document-specific fields (APN, ordinance number, meeting date, ...)
    that Source/Document have.
    """

    __tablename__ = "news_sources"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(Text, nullable=False)
    outlet_url: Mapped[str] = mapped_column(Text, nullable=False)
    rss_feed_url: Mapped[str] = mapped_column(Text, nullable=False)
    connector: Mapped[str] = mapped_column(Text, nullable=False)  # "wordpress_rss" | "google_news_proxy"
    polling_interval_minutes: Mapped[int] = mapped_column(Integer, default=60)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    articles: Mapped[list["NewsArticle"]] = relationship(back_populates="news_source")


class NewsArticle(Base):
    """A single retrieved+classified news article. `full_text`/`archive_path`
    are only ever populated when `news_source.connector == "wordpress_rss"`
    -- see core/app/news/retrieval.py.
    """

    __tablename__ = "news_articles"

    id: Mapped[uuid.UUID] = uuid_pk()
    news_source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("news_sources.id"))
    title: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    summary: Mapped[str | None] = mapped_column(Text)
    full_text: Mapped[str | None] = mapped_column(Text)
    archive_path: Mapped[str | None] = mapped_column(Text)
    topic_categories: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    classification_method: Mapped[str] = mapped_column(Text, nullable=False)  # "heuristic" | "ai"
    classification_confidence: Mapped[str] = mapped_column(Text, nullable=False)  # "low" | "medium" | "high"

    news_source: Mapped["NewsSource"] = relationship(back_populates="articles")
