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
- **Entity resolution** (`resolution.py`): deterministic matching only --
  exact normalized canonical-name and accepted-alias tiers, scoped by
  `entity_type`. The PRD's third tier ("high-confidence contextual match
  requiring review") is fuzzy/AI-adjacent and deferred; `resolve_entity`
  returning `None` means "no confident match," not "definitely new."
- **Reconciliation** (`reconciliation.py`): deterministic classification
  of a resolved assertion against `org_relationships` --
  confirming/adding/contradicting/duplicating/unresolved. Scoped to
  relationship-type assertions (e.g. `occupies_position`); reconciling a
  unit/position *attribute* change (a rename) against its own version
  history is a separate, not-yet-built case.
- **Extraction** (`extraction.py`): turns a parsed document into candidate
  `OrgSourceAssertion` rows via the local Ollama layer (new
  `org_assertion_extraction` prompt in `app/ai/prompts.py`, same
  Prompt-row + degrade-to-nothing pattern as `app/ai/classify.py`), then
  resolves each claim's subject/object text against known entities.
  Verified live against a real Ventura City Council minutes document
  (correctly extracted the City Manager/City Attorney/City Clerk roster
  with accurate quoted passages and evidence_mode). Extraction never
  touches accepted state -- it only creates assertions.
- **Event drafting** (`event_drafting.py`): turns a reconciled assertion
  into a proposed `OrgEvent` -- nothing for CONFIRMING/DUPLICATING/
  UNRESOLVED (no new, reviewable change). Deliberately conservative about
  event_type: any assertion whose `evidence_mode` isn't `"explicit"`
  always becomes `unexplained_state_change`, never a claimed specific
  personnel action, matching the PRD's "never infer... unless directly
  source-supported" guardrail. CONTRADICTING on `occupies_position`
  becomes `reassigned` (succession); everything else follows a
  predicate→event_type table. Every drafted event still lands `pending`
  in `review_status` -- nothing here approves anything.
- **Pipeline orchestration** (`pipeline.py`): `process_document_for_organization`
  chains extract → (resolve, already inside extraction) → draft-event-per-
  assertion for one document. Not yet wired into `worker.py` as an
  ongoing step -- callable directly today.
- **Minimal read API** (`routers.py`): all eight endpoints listed in the
  PRD, including point-in-time structure (`?at=YYYY-MM-DD`) with resolved
  position occupants.
- **Tests**: temporal versioning correctness, point-in-time relationship
  queries across a succession, assertion correction history, the event
  review lifecycle, entity resolution tiers, reconciliation
  classification (including the object-side/succession conflict case --
  found and fixed live while writing `event_drafting.py`'s own test),
  extraction (mocked Ollama, matching `test_classify.py`'s pattern), event
  drafting, and the full pipeline. Verified live end-to-end against real
  Ventura documents and entities: extraction (real City Council minutes,
  correctly pulled the City Manager/City Attorney/City Clerk roster),
  ADDING (a genuinely new appointment), and CONTRADICTING/succession (a
  second person asserted into an already-occupied position) all produced
  correct, appropriately-worded drafted events.

## Explicitly deferred (not in this pass)

- **Fuzzy/contextual entity resolution**: resolution's third PRD tier.
  `_resolve_best_guess` in `extraction.py` also only tries exact/alias
  matching across a fixed type-priority order (person, then position,
  unit, organization) -- a real ambiguity (two people with the same name)
  isn't disambiguated by context today.
- **Dashboard UI** (`templates/`): the PRD's Organization overview, Entity
  detail, Change log and Review queue pages don't exist yet -- everything
  above is reachable via the API only.
- **Ventura source configuration** (`cities/ventura/organization_sources.py`
  in the PRD's implementation boundary): extraction runs against whatever
  document is passed to it, but nothing yet selects which of Ventura's
  documents should feed it as an ongoing pipeline step (e.g. a worker
  hook analogous to `classify_document`'s).
- **Duplicate-assertion detection across documents**: reconciliation's
  `DUPLICATING` check is scoped to the same `document_id` -- the same
  claim re-extracted from two different documents (e.g. an agenda and its
  minutes) isn't caught as a duplicate today.
- **Single-occupant cardinality is hardcoded to one predicate**:
  reconciliation's object-side conflict check (a position already has a
  different occupant) only applies to `occupies_position` --
  `_SINGLE_OCCUPANT_PREDICATES` would need extending if another predicate
  later needs the same treatment (e.g. a Mayor-like single-seat `member_of`
  case).
- **Not wired into `worker.py`**: nothing runs extraction/reconciliation/
  event-drafting automatically as documents get parsed -- `pipeline.py` is
  callable but not yet scheduled.

Building any of the above should follow the same principle the tests
check for: a write is a new version/row, never a mutation that could lose
what was true before.
