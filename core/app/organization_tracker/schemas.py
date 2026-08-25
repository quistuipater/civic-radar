from datetime import date, datetime

from pydantic import BaseModel


class EntityOut(BaseModel):
    id: str
    entity_type: str
    canonical_name: str
    aliases: list[str] | None = None


class OrganizationOut(EntityOut):
    org_type: str
    jurisdiction: str | None
    status: str
    valid_from: date
    valid_to: date | None


class UnitOut(EntityOut):
    organization_entity_id: str
    unit_type: str
    parent_unit_entity_id: str | None
    status: str
    valid_from: date
    valid_to: date | None


class PositionOut(EntityOut):
    organization_entity_id: str
    unit_entity_id: str | None
    title: str
    position_type: str
    status: str
    authorized_count: int | None
    valid_from: date
    valid_to: date | None
    # Current occupant(s) as of the query date, if any -- resolved from
    # org_relationships(occupies_position), not stored on PositionVersion
    # itself (a position persists independently of who holds it).
    occupants: list[EntityOut] = []


class OrganizationStructureOut(BaseModel):
    as_of: date
    organization: OrganizationOut
    units: list[UnitOut]
    positions: list[PositionOut]


class OrgEventOut(BaseModel):
    id: str
    organization_entity_id: str
    event_type: str
    effective_date: date | None
    observed_date: date
    title: str
    narrative: str
    certainty: str
    review_status: str
    reviewer_note: str | None
    created_at: datetime
    reviewed_at: datetime | None


class OrgSourceAssertionOut(BaseModel):
    id: str
    document_id: str
    subject_text: str
    subject_entity_id: str | None
    predicate: str
    object_text: str | None
    object_entity_id: str | None
    assertion_type: str
    effective_date: date | None
    observed_at: datetime
    evidence_mode: str
    source_authority: str | None
    extraction_method: str
    confidence: str | None
    review_status: str
    superseded_assertion_id: str | None
