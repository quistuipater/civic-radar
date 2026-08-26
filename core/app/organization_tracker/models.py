"""Organization Tracker's schema (docs/organization-tracker/MVP-PRD.md).

Extends the existing entities/entity_mentions tables (app/models.py) rather
than forking a parallel identity system, per the PRD's "Existing entity
schema" section -- Person, Organization, Organizational unit and Position
are all `entities` rows (entity_type = "person" | "organization" |
"organizational_unit" | "position"); a Person needs no detail table at all
since Entity's own canonical_name/aliases/notes already cover the PRD's
"Person" minimum fields.

Organization, Unit and Position each carry a *version* table here rather
than mutable columns on Entity itself: "current state never destroys
history" (PRD) means a name/parent/status change closes the current version
(sets valid_to) and opens a new one, rather than overwriting a value in
place. `service.py` is the only code that should write these tables.
"""

import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models import uuid_pk


class OrganizationVersion(Base):
    """One valid-time slice of an Organization entity's own attributes.

    entity_id is NOT unique -- an organization with more than one version
    over time has more than one row here, at most one with valid_to IS NULL
    (the current version). See service.py's _close_open_version_query.
    """

    __tablename__ = "org_organization_versions"

    id: Mapped[uuid.UUID] = uuid_pk()
    entity_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("entities.id"), nullable=False, index=True)
    org_type: Mapped[str] = mapped_column(Text, nullable=False)
    parent_entity_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("entities.id"))
    jurisdiction: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active")
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UnitVersion(Base):
    """One valid-time slice of an Organizational unit's own attributes."""

    __tablename__ = "org_unit_versions"

    id: Mapped[uuid.UUID] = uuid_pk()
    entity_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("entities.id"), nullable=False, index=True)
    organization_entity_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("entities.id"), nullable=False)
    canonical_name: Mapped[str] = mapped_column(Text, nullable=False)
    unit_type: Mapped[str] = mapped_column(Text, nullable=False)
    parent_unit_entity_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("entities.id"))
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active")
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PositionVersion(Base):
    """One valid-time slice of a Position's own attributes (title, unit,
    status, authorized count) -- distinct from *occupancy*, which is an
    OrgRelationship ("occupies_position") between a Person entity and this
    Position entity, since a position persists independently of who (if
    anyone) currently holds it.
    """

    __tablename__ = "org_position_versions"

    id: Mapped[uuid.UUID] = uuid_pk()
    entity_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("entities.id"), nullable=False, index=True)
    organization_entity_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("entities.id"), nullable=False)
    unit_entity_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("entities.id"))
    title: Mapped[str] = mapped_column(Text, nullable=False)
    position_type: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active")
    authorized_count: Mapped[int | None] = mapped_column(Integer)
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# PRD's relationship-type vocabulary: occupies_position, member_of,
# reports_to_position, unit_reports_to_unit, appoints, oversees, part_of,
# succeeded_by. Not a DB-level enum (same convention as entity_type on
# Entity, authority_level on Source/NewsSource elsewhere in this codebase)
# so a new type doesn't require a migration.
class OrgRelationship(Base):
    """A time-bounded relationship between two entities (PRD "Relationship")."""

    __tablename__ = "org_relationships"

    id: Mapped[uuid.UUID] = uuid_pk()
    subject_entity_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("entities.id"), nullable=False, index=True)
    relationship_type: Mapped[str] = mapped_column(Text, nullable=False)
    object_entity_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("entities.id"), nullable=False, index=True)
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OrgSourceAssertion(Base):
    """An immutable claim made or supported by a source (PRD "Source assertion").

    Immutable in the sense that corrections create a new row with
    superseded_assertion_id pointing at the one it replaces -- never an
    UPDATE of subject/predicate/object on an existing row.
    """

    __tablename__ = "org_source_assertions"

    id: Mapped[uuid.UUID] = uuid_pk()
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id"), nullable=False, index=True)
    chunk_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("document_chunks.id"))
    page_number: Mapped[int | None] = mapped_column(Integer)
    section: Mapped[str | None] = mapped_column(Text)
    media_timestamp_seconds: Mapped[int | None] = mapped_column(Integer)
    quoted_passage: Mapped[str | None] = mapped_column(Text)
    assertion_type: Mapped[str] = mapped_column(Text, nullable=False)
    # subject/object are free text until entity resolution runs (see PRD
    # "Entity resolution") -- *_entity_id is filled in once resolved, and
    # left null for an assertion about a not-yet-created candidate entity.
    subject_text: Mapped[str] = mapped_column(Text, nullable=False)
    subject_entity_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("entities.id"))
    predicate: Mapped[str] = mapped_column(Text, nullable=False)
    object_text: Mapped[str | None] = mapped_column(Text)
    object_entity_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("entities.id"))
    effective_date: Mapped[date | None] = mapped_column(Date)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    evidence_mode: Mapped[str] = mapped_column(Text, nullable=False)  # explicit | derived | inferred
    source_authority: Mapped[str | None] = mapped_column(Text)
    extraction_method: Mapped[str] = mapped_column(Text, nullable=False)
    model_name: Mapped[str | None] = mapped_column(Text)
    prompt_version: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[str | None] = mapped_column(Text)
    review_status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    superseded_assertion_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("org_source_assertions.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OrgEvent(Base):
    """A reviewed explanation of a change (PRD "Organizational event")."""

    __tablename__ = "org_events"

    id: Mapped[uuid.UUID] = uuid_pk()
    organization_entity_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("entities.id"), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    effective_date: Mapped[date | None] = mapped_column(Date)
    observed_date: Mapped[date] = mapped_column(Date, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    narrative: Mapped[str] = mapped_column(Text, nullable=False)
    certainty: Mapped[str] = mapped_column(Text, nullable=False)
    review_status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    reviewer_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OrgEventAssertion(Base):
    """Junction: which source assertions support a given event."""

    __tablename__ = "org_event_assertions"

    id: Mapped[uuid.UUID] = uuid_pk()
    event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("org_events.id"), nullable=False, index=True)
    assertion_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("org_source_assertions.id"), nullable=False)


class OrgEventEntity(Base):
    """Junction: which entities (people, positions, units...) an event affects."""

    __tablename__ = "org_event_entities"

    id: Mapped[uuid.UUID] = uuid_pk()
    event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("org_events.id"), nullable=False, index=True)
    entity_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("entities.id"), nullable=False)


class OrgDocumentProcessing(Base):
    """Marks a document as already run through the org-tracker pipeline
    (pipeline.py's run_batch), independent of whether it produced any
    assertions -- a document with zero organizational content is a valid,
    final outcome, not something to retry every tick forever. Deliberately
    not a column on the shared Document model: this is an org-tracker-
    specific concern, kept namespaced to this module's own tables per the
    PRD's "clearly namespaced" requirement.
    """

    __tablename__ = "org_document_processing"

    id: Mapped[uuid.UUID] = uuid_pk()
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id"), nullable=False, unique=True, index=True)
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    organizations_matched: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    assertions_created: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    events_drafted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
