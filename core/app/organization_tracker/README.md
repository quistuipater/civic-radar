# Organization Tracker — implementation status

See `docs/organization-tracker/MVP-PRD.md` for the full product spec. This
note tracks what's actually built versus what the PRD describes but this
first implementation pass deliberately left out.

## Implemented

- **Data model** (`models.py`): versioned `OrganizationVersion`/
  `UnitVersion`/`PositionVersion` tables keyed to `entities.id` (extends
  the existing `entities`/`entity_mentions` tables rather than forking a
  parallel identity system), `OrgRelationship`, `OrgSourceAssertion`
  (immutable, corrections supersede rather than mutate), `OrgEvent` plus
  its assertion/entity junction tables.
- **Write path** (`service.py`): create organization/unit/position/person,
  rename-or-transfer a unit, revise a position, start/end/replace a
  relationship, record an assertion (with supersession), propose and
  review an event (approve/reject/defer). Every mutation follows "current
  state never destroys history" -- a changed attribute closes the open
  version and opens a new one, never an in-place UPDATE of a value.
- **Minimal read API** (`routers.py`): all eight endpoints listed in the
  PRD, including point-in-time structure (`?at=YYYY-MM-DD`) with resolved
  position occupants.
- **Tests** (`tests/organization_tracker/test_service.py`): temporal
  versioning correctness, point-in-time relationship queries across a
  succession, assertion correction history, and the event review
  lifecycle.

## Explicitly deferred (not in this pass)

- **Extraction** (`extraction.py` in the PRD's implementation boundary):
  turning a parsed document into candidate assertions via the local AI
  layer. Nothing here calls Ollama.
- **Entity resolution** (`resolution.py`): matching a candidate name to an
  existing `entities` row versus creating a new one. `service.py`'s
  `create_person`/`create_unit`/`create_position` always create a new
  entity -- there's no dedup/matching logic yet.
- **Reconciliation** (`reconciliation.py`): classifying a new assertion
  against accepted state (confirms / contradicts / proposes an event /
  duplicate / ...) and auto-drafting an event from it. `service.py`'s
  `propose_event` requires the caller to already know what happened;
  nothing infers a candidate event from an assertion automatically today.
- **Dashboard UI** (`templates/`): the PRD's Organization overview, Entity
  detail, Change log and Review queue pages don't exist yet -- everything
  above is reachable via the API only.
- **Ventura source configuration** (`cities/ventura/organization_sources.py`
  in the PRD's implementation boundary): no Ventura-specific source list
  or seed data yet.
- **Duplicate-assertion detection**: the PRD's reliability requirement
  ("detect duplicate assertions") belongs to reconciliation, not the write
  path -- `record_assertion` will happily create two identical assertions
  if called twice.

Building any of the above should follow the same principle the tests
check for: a write is a new version/row, never a mutation that could lose
what was true before.
