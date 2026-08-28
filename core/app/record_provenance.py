"""Ontology for public records and the representations Civic Radar acquires.

A downloaded PDF, HTML page, API response, scan, emailed copy or counter copy
is not necessarily the underlying public record. It is a *representation* of
that record and may be redacted, incomplete, transformed or otherwise lossy.

This distinction matters whenever Civic Radar reasons from absence. A value
missing from a redacted online representation is not evidence that the value
was absent from the filed or official record.
"""

import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models import uuid_pk


class PublicRecord(Base):
    """The underlying filed, issued or maintained public record.

    This is the conceptual record independent of how Civic Radar obtained it.
    A single public record may have several representations: a redacted web
    copy, an API rendering, a clerk-provided unredacted copy, a scan, etc.
    """

    __tablename__ = "public_records"

    id: Mapped[uuid.UUID] = uuid_pk()
    record_type: Mapped[str] = mapped_column(Text, nullable=False)
    record_identifier: Mapped[str | None] = mapped_column(Text, index=True)
    jurisdiction: Mapped[str | None] = mapped_column(Text, index=True)
    agency: Mapped[str | None] = mapped_column(Text, index=True)
    record_date: Mapped[date | None] = mapped_column(Date)

    # Public-access semantics describe the underlying record, not a specific
    # online copy. Examples: public, conditionally_public, confidential,
    # unknown. `access_basis` can cite the governing statute, regulation,
    # ordinance or agency policy.
    legal_access_status: Mapped[str] = mapped_column(Text, nullable=False, default="unknown")
    access_basis: Mapped[str | None] = mapped_column(Text)
    unredacted_available: Mapped[bool | None] = mapped_column(Boolean)
    unredacted_access_method: Mapped[str | None] = mapped_column(Text)

    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class RecordRepresentation(Base):
    """One acquired representation of an underlying public record.

    `document_id` points at Civic Radar's immutable archived artifact. The
    representation records what kind of copy that artifact is and whether it
    is known to be complete. This prevents the archived Document object from
    being mistaken for the legal or official record itself.
    """

    __tablename__ = "record_representations"

    id: Mapped[uuid.UUID] = uuid_pk()
    public_record_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("public_records.id"), nullable=False, index=True
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id"), nullable=False, unique=True, index=True
    )

    # Suggested vocabulary, intentionally not DB enums:
    # representation_type: web_publication | api_rendering | filed_original |
    # clerk_copy | scan | email_copy | other
    # completeness: complete | redacted | excerpt | transformed | unknown
    # redaction_status: none | partial | full | unknown
    representation_type: Mapped[str] = mapped_column(Text, nullable=False)
    completeness: Mapped[str] = mapped_column(Text, nullable=False, default="unknown")
    redaction_status: Mapped[str] = mapped_column(Text, nullable=False, default="unknown")
    redaction_authority: Mapped[str | None] = mapped_column(Text)
    redaction_method: Mapped[str | None] = mapped_column(Text)  # automated | manual | mixed | unknown
    redaction_basis: Mapped[str | None] = mapped_column(Text)

    # How this representation was acquired and any gate imposed on access.
    # Examples: public_web, public_api, email_request, counter_inspection,
    # mailed_copy, CPRA_request. `access_constraints` is descriptive, not a
    # claim that a constraint is lawful.
    retrieval_method: Mapped[str | None] = mapped_column(Text)
    access_constraints: Mapped[str | None] = mapped_column(Text)
    acquired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RecordRepresentationGap(Base):
    """A known difference, omission or suppression in a representation.

    A gap is explicit provenance. It distinguishes "not present in this copy"
    from "not present in the underlying record" and allows later comparison
    against an unredacted or otherwise more complete representation.
    """

    __tablename__ = "record_representation_gaps"

    id: Mapped[uuid.UUID] = uuid_pk()
    representation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("record_representations.id"), nullable=False, index=True
    )
    page_number: Mapped[int | None] = mapped_column(Integer)
    field_label: Mapped[str | None] = mapped_column(Text)
    content_category: Mapped[str | None] = mapped_column(Text)

    # gap_type: redaction | omission | truncation | unavailable_attachment |
    # transformation_loss | unknown
    # cause: privacy | statutory | filing_officer_policy | vendor_automation |
    # collateral | unknown
    gap_type: Mapped[str] = mapped_column(Text, nullable=False)
    cause: Mapped[str | None] = mapped_column(Text)
    mechanism: Mapped[str | None] = mapped_column(Text)  # automated | manual | mixed | unknown
    policy_basis: Mapped[str | None] = mapped_column(Text)
    verification_status: Mapped[str] = mapped_column(Text, nullable=False, default="observed")
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint(
            "representation_id",
            "page_number",
            "field_label",
            "gap_type",
            name="uq_record_representation_gap",
        ),
    )
