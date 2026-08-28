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
  assertion for one document. `run_batch()` is the ongoing-operation
  entrypoint -- matches each not-yet-processed parsed document to every
  currently-tracked organization sharing its `jurisdiction` string,
  processes it, and marks it done (`OrgDocumentProcessing`) even if zero
  organizations matched or zero assertions were extracted, so a document
  with no organizational content isn't retried forever. Deliberately
  jurisdiction-agnostic, not Ventura-specific in code -- a city with no
  organizations seeded (Santa Cruz, Boston) just no-ops.
- **Wired into `worker.py`**: `run_organization_tracker_batch()` runs every
  tick, after `run_news_batch()`.
- **Cross-document duplicate detection**: reconciliation now also checks
  for the same claim already sitting in a *pending* drafted event from any
  document, not just the same one -- without this, the same well-known
  fact (an incumbent's name recurring on every meeting's roster) drafted a
  fresh near-identical event every time it was re-extracted. A rejected
  (not pending) prior proposal doesn't suppress a later restatement.
- **Minimal read API** (`routers.py`): all eight endpoints listed in the
  PRD, including point-in-time structure (`?at=YYYY-MM-DD`) with resolved
  position occupants.
- **Dashboard UI** (`dashboard.py` + `templates/organization_{list,detail,review,changes}.html`
  + `templates/entity_detail.html`):
  `/organizations` (list, with a pending-review badge per org),
  `/organizations/{id}` (current structure, or `?at=` for a past date, with
  every position/occupant cross-linked to its entity detail page),
  `/organizations/{id}/review` (pending events with evidence, source-document
  links, and Approve/Reject/Defer), `/organizations/{id}/changes` (reviewed
  events -- approved/rejected/deferred -- filterable by type/certainty/
  status), `/entities/{id}` (one person/position/unit's full relationship
  history in both directions, associated events, and source assertions).
  **Approving now applies the event's
  underlying relationship to accepted state in the same transaction**
  (`service._apply_approved_event`) -- the PRD's "Acceptance is
  transactional... commit together." Added while building the UI, since
  shipping an Approve button that only changed a status label without
  updating the org chart would have been misleading. Handles subject-side
  supersede (moved to a different position) and object-side supersede
  (succession), the same conflict logic reconciliation itself uses.
  `unexplained_state_change` events never auto-apply, even on approval --
  approving one means "worth keeping on record," not "I know what
  happened." Verified live via the real form endpoint: rejected 4 real
  pending events (see below) and confirmed the org chart was untouched;
  approved a real test event and confirmed the relationship was created
  with the correct effective date and prior-occupant closure.
- **Tests**: temporal versioning correctness, point-in-time relationship
  queries across a succession, assertion correction history, the event
  review lifecycle, entity resolution tiers, reconciliation classification
  (object-side/succession conflicts, cross-document dedup, the
  3+-identical-assertions-in-one-document crash), extraction (mocked
  Ollama), event drafting, and the full pipeline including `run_batch`.
  Verified live end-to-end against real Ventura documents and entities,
  including catching two real bugs live testing exposed that no unit test
  had covered yet (see below) and confirming the fixes against the actual
  documents that had triggered them.

## Ventura baseline

`cities/ventura/organization_baseline.py` seeds a reviewed baseline (PRD
MVP goal #1) directly through `service.py`, not the assertion/review
pipeline -- this is an operator asserting already-known state, not AI
output awaiting review. Every name/title was verified live 2026-08-27
against two independent sources: the City's own directory pages
(cityofventura.ca.gov) and real archived Council minutes already in this
project's document archive. Currently seeded: City of Ventura, all 7
Council district seats + Mayor/Deputy Mayor (rotating titles, not
separate seats -- see the script's docstring), City Manager, City
Attorney, City Clerk, and their current occupants (10 people total). Run
once, live, via `docker cp` + `docker exec ... python organization_baseline.py`
(not yet wired into `seed_sources.py`'s bind-mount pattern -- a one-off
so far, not part of the regular per-city deploy flow).

`cities/ventura/organization_departments_baseline.py` (run after the above,
2026-08-27) extends this with the 10 department/division-level units the
first baseline pass left unpopulated -- Finance, HR, IT, Community
Development, Fire, Parks & Recreation, Police, Public Works, Ventura
Water, and Economic Development, each with a `Position`/occupant for its
current director, verified the same way (city department pages plus at
least one independent news source per name). Same idempotent,
straight-through-`service.py` pattern and caveats as the council baseline
above. The organization detail page's positions table now shows each
position's unit (renamed from "Council / Leadership" to "Positions" since
it now mixes elected seats and department directors).

Running `pipeline.run_batch` against this baseline live (both manually and
via the worker's own tick loop, unattended) confirmed the whole loop works
correctly: most real documents restating already-known facts correctly
classified CONFIRMING and drafted nothing. Four real events did get
drafted from the worker's own unattended run, and all four turned out to
be genuine AI extraction errors on messy real text -- e.g. Bill Ayub
misattributed to City Attorney instead of City Manager from a bare
table-header line, and Michael B. MacDonald's predicate extracted as
"appoints" with a quoted passage that was actually unrelated Zoom
dial-in instructions. All four sat `pending` rather than corrupting
accepted state, and were reviewed and rejected through the real dashboard
form endpoint (`/organizations/{id}/events/{id}/review`) -- confirmed the
org chart was untouched afterward. This is the extraction-quality
limitation noted above ("AI extraction is not always valid JSON") showing
up in a milder form: even when the JSON parses, the *content* can still be
wrong on ambiguous source text, which is exactly why nothing here
auto-applies without review.

## Known limitations (real, found during live testing -- not yet fixed)

- **Multi-column rosters flattened onto one line can still mis-pair names
  and titles**, even after the `org_assertion_extraction` prompt (v2, added
  2026-08-27) was tightened with an explicit rule and worked example. The
  real trigger was a Ventura agenda roster
  (`_06032024-3208`) where a two-column attendee list collapsed into single
  lines like "Joe Schroeder, Mayor Meredith Hart, Economic Development
  Manager" -- pdfplumber's `extract_text()` reads left-to-right by
  y-position with no table/column awareness, so the source text itself
  loses the column boundary. v1 of the prompt mis-paired every second
  person with the *first* title on the line rather than their own; v2's
  explicit worked example (matching this exact document) fixed all 5 pairs
  on live re-extraction. Not fixed at the root: pdfplumber is never told
  this is a table, so a differently-worded multi-column roster from another
  city could still confuse the model the same way -- prompt-level guidance
  is a mitigation, not a structural fix. A more robust fix would extract
  column layout via `page.extract_table()`/`.extract_words()` with x/y
  coordinates instead of flat `extract_text()`, at least for roster-shaped
  pages, but that's real parsing work, not attempted here.
- **AI extraction is not always valid JSON.** On real (longer/more complex)
  documents, the model sometimes returns malformed JSON that fails to
  parse -- `extraction.py` catches this and returns no assertions for that
  document rather than crashing, but that document's organizational
  content is then silently missed until the prompt/model/parsing is
  improved. Worth monitoring `org assertion extraction failed... invalid
  JSON` in worker logs.
- **`run_batch()` is not safe to run concurrently** against the same
  database -- confirmed live 2026-08-26 that two overlapping invocations
  (an accidentally-orphaned background process plus a fresh one) raced on
  `OrgDocumentProcessing`'s unique constraint. Not a problem for the
  single `worker.py` tick loop (which never overlaps itself), but don't
  invoke `run_batch` manually while the worker is also running, or from
  more than one script/process at once.

## Explicitly deferred (not in this pass)

- **Fuzzy/contextual entity resolution**: resolution's third PRD tier.
  `_resolve_best_guess` in `extraction.py` also only tries exact/alias
  matching across a fixed type-priority order (person, then position,
  unit, organization) -- a real ambiguity (two people with the same name)
  isn't disambiguated by context today.
- **"Before/after state" on the change log**: the PRD's Change log spec
  says "every approved entry opens to before/after state" -- there's no
  stored snapshot pair to diff against, so `/organizations/{id}/changes`
  shows the event's narrative and evidence plus a link to the affected
  entity's *current* state, not a captured before/after comparison.
- **Ventura source configuration** (`cities/ventura/organization_sources.py`
  in the PRD's implementation boundary): `run_batch` processes every
  parsed document sharing a tracked organization's jurisdiction string --
  there's no source-level allowlist/denylist yet if that turns out to be
  too broad or too narrow in practice.
- **Single-occupant cardinality is hardcoded to one predicate**:
  reconciliation's object-side conflict check (a position already has a
  different occupant) only applies to `occupies_position` --
  `_SINGLE_OCCUPANT_PREDICATES` would need extending if another predicate
  later needs the same treatment (e.g. a Mayor-like single-seat `member_of`
  case).

Building any of the above should follow the same principle the tests
check for: a write is a new version/row, never a mutation that could lose
what was true before.
