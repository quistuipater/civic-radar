# Organization Tracker MVP Product Requirements

**Status:** Proposed  
**Initial deployment:** City of San Buenaventura (City of Ventura)  
**Repository boundary:** Bounded module within Civic Radar  
**Version:** 0.1 — 2026-08-24

## Product summary

Organization Tracker creates a source-linked historical record of how an
organization is structured, who occupies its positions, and how that state
changes over time.

The MVP consumes documents and extracted text already collected by Civic
Radar. It identifies organizational claims, resolves them to canonical
entities, compares them with accepted organizational state and proposes change
events for human review. Approved events update the accepted state and become
part of an auditable organizational history.

The City of Ventura is the first tracked organization. The model must remain
jurisdiction-independent so it can later support other governments, federal
agencies, companies, nonprofits and related bodies.

## Problem

Organizational information is distributed across directories, leadership
pages, organization charts, budgets, agendas, staff reports, resolutions,
ordinances, job postings, press releases, meeting recordings and news
coverage. These sources frequently disagree, omit effective dates or update
without explaining what changed.

A conventional organization chart only describes a current snapshot. It
cannot reliably answer:

- What did the organization look like on a particular date?
- Who occupied a position and during what period?
- When was a unit or position created, renamed, transferred or eliminated?
- Which evidence supports each claim?
- Was a change explicitly announced or merely inferred from a changed page?
- What remains uncertain or disputed?

The system must preserve evidence and uncertainty rather than overwrite old
facts with newly observed values.

## Relationship to Civic Radar

Organization Tracker is part of the Civic Radar monorepo but is a distinct
bounded module.

Civic Radar remains responsible for:

- source registration and scheduled retrieval;
- immutable raw HTML, PDF, audio, video and metadata archival;
- hashing, deduplication, parsing, OCR, transcription and document chunks;
- source health and provenance;
- existing operator-review conventions.

Organization Tracker is responsible for:

- extracting proposed organizational assertions from Civic Radar documents;
- resolving people, organizations, units, positions and memberships;
- maintaining time-aware accepted organizational state;
- detecting contradictions and candidate changes;
- drafting source-linked change events;
- presenting assertions and events for human review;
- exposing current structure and historical state through UI and API.

The MVP may share the existing PostgreSQL instance and worker process, but its
tables, services, routes, templates and tests must be clearly namespaced. Core
business logic must contain no Ventura-specific identifiers.

## Product principles

### Evidence before interpretation

Every assertion and event must link to an archived Civic Radar document and,
where possible, a page, section, timestamp or quoted passage. A URL without
archived evidence is insufficient.

### Observations are not necessarily events

A directory changing from one name to another proves that the page changed. It
does not, by itself, prove why, when the personnel action became effective or
whether the prior occupant resigned, retired, was terminated or was
reassigned.

### Current state never destroys history

Accepted relationships are closed with an end date or superseded by a new
version. They are not overwritten in a way that loses previous state.

### Source facts and inference remain distinct

The system records whether a claim is explicit, derived or inferred. Language
such as “promoted,” “demoted,” “terminated” or “resigned” requires explicit
support from an appropriate source.

### Human review controls accepted state

AI output creates proposals. It does not directly modify accepted
organizational state or publish a factual event.

### Local-first operation

Extraction and reconciliation must work with the local Ollama-backed AI layer.
Cloud models may later be optional escalation paths but are not an MVP
dependency.

## Users

The primary user is the Civic Radar operator, who reviews proposed entities,
identity matches, assertions, conflicts and events; corrects errors; and
approves changes to accepted state.

A later read-only user may inspect current organization, historical snapshots,
the change log and supporting evidence. Public access and subscriptions are
outside the MVP.

## MVP goals

The MVP must:

- create a reviewed baseline model of the City of Ventura;
- represent organizations, units, positions, people, memberships and
  reporting or oversight relationships;
- retain both effective time and observation time;
- extract organizational assertions from selected Civic Radar documents;
- detect additions, removals, replacements, renames and relationship changes;
- distinguish explicit events from unexplained observed differences;
- create source-linked candidate event narratives;
- provide an operator review workflow;
- show current structure, entity history and an event log;
- expose a minimal read API;
- operate within the existing Ventura deployment without a separate service.

## Non-goals

The MVP will not:

- build a general-purpose graph database;
- infer private or unpublished employment actions;
- monitor personal social-media accounts;
- claim motive, misconduct, promotion or demotion from title changes alone;
- calculate informal influence networks;
- model every city employee;
- replace Civic Radar ingestion, archive, parsing or review infrastructure;
- publish automatically to a public website;
- send alerts or newsletters;
- support arbitrary companies or federal agencies in the initial UI;
- reconstruct a complete historical organization before the baseline date;
- automatically merge ambiguous people without review.

## Ventura scope

The reviewed baseline should include:

- City of San Buenaventura;
- City Council, council districts and current council members;
- City Manager's Office;
- City Attorney's Office and City Clerk;
- all city departments and department heads;
- major named divisions and publicly identified division heads;
- standing boards, commissions and committees;
- current members when authoritative rosters are available;
- appointing, reporting and oversight relationships;
- acting, interim, vacant and permanent positions;
- stated term dates for elected and appointed memberships.

Contractors and partner organizations may be represented when their
institutional relationship is material, but complete contractor staffing is
outside scope.

### Initial source classes

Civic Radar should ingest or already hold:

1. City leadership, department and staff-directory pages.
2. City Council agendas, minutes, staff reports, resolutions and ordinances.
3. Adopted budgets, authorized-position schedules and organization charts.
4. Board, commission and committee rosters and appointment actions.
5. City Charter and Municipal Code provisions establishing authority.
6. Employment agreements and official appointment announcements.
7. Job classifications, recruitment announcements and vacancy reports.
8. Conflict-of-interest code and designated-position lists.
9. Official newsroom releases and meeting transcripts.
10. Reputable news reporting used only as secondary evidence.

The source registry must identify authority level, expected update cadence,
organization coverage and whether a source describes current state or formal
action.

## Conceptual data model

Use relational tables with stable UUID identifiers. A dedicated graph database
is not required.

### Organization

A legal, administrative, commercial or civic body.

Minimum fields: ID, canonical name, organization type, optional parent,
jurisdiction, status, valid-from and valid-to.

### Organizational unit

A department, office, division, bureau, board, commission, committee, team or
other component.

Minimum fields: ID, organization ID, canonical name, unit type, optional
parent unit and status. Names and parent relationships must be versioned when
they change.

### Position

A role that may exist independently of any occupant.

Minimum fields: ID, organization ID, optional unit ID, canonical title,
position type, status and optional authorized count.

Examples include City Manager, Public Works Director, Council Member for
District 3 and Planning Commissioner.

### Person

A canonical identity for an individual named in organizational evidence.

Minimum fields: ID, display name, normalized name and optional disambiguation
note. Sensitive personal information is neither required nor collected merely
to improve matching.

### Relationship

A time-bounded relationship between entities. Types include:

- occupies position;
- member of;
- reports to position;
- unit reports to unit;
- appoints;
- oversees;
- part of;
- succeeded by.

Minimum fields: ID, typed subject, relationship type, typed object,
valid-from, valid-to and status.

### Source assertion

An immutable claim made or supported by a source. Corrections create a
superseding assertion.

Minimum fields:

- ID, document ID and optional chunk ID;
- page, section or media timestamp;
- optional quoted passage;
- assertion type and structured subject, predicate and object;
- optional effective date and required observation time;
- evidence mode: explicit, derived or inferred;
- source authority and extraction method;
- optional model and prompt version;
- confidence and review status;
- optional superseded-assertion ID.

### Organizational event

A reviewed explanation of a change.

Minimum fields:

- ID, organization ID and event type;
- optional effective date and required observed date;
- title and evidence-bounded narrative;
- certainty and review status;
- created and reviewed timestamps;
- optional reviewer note.

Each event links to one or more assertions and affected entities or
relationships.

### Bitemporal requirement

The system distinguishes valid time—when a fact was true in the world—from
system time—when Civic Radar observed, accepted, corrected or superseded it.
Unknown dates remain unknown or explicitly approximate. An ingestion date
must not silently become an effective date.

## Event taxonomy

Personnel and membership events:

- appointed, elected, hired, assigned or reappointed;
- term started or expired;
- resigned, retired or departed with reason unspecified;
- terminated, promoted or demoted only with explicit evidence;
- acting assignment started or ended;
- vacancy opened or filled;
- reassigned.

Position and unit events:

- position created, eliminated, renamed or transferred;
- unit created, dissolved, renamed, merged, split or transferred;
- reporting relationship changed;
- responsibility transferred.

When evidence shows a difference but not the underlying event, the system
creates an unexplained-state-change candidate. Its narrative states exactly
what changed in the evidence and what remains unknown.

## Extraction and reconciliation

### Candidate extraction

When a qualifying document reaches parsed state, the extractor receives its
identifier and relevant chunks and returns structured candidate assertions
using a versioned schema. It should favor precise, atomic claims.

### Entity resolution

Resolution proceeds by stable source identifier, accepted alias, exact
normalized identity plus compatible context, high-confidence contextual match
requiring review, then creation of a candidate entity.

Name similarity alone may not automatically merge people. Canonical labels
remain operator-controlled.

### Reconciliation

The reconciler classifies an assertion as:

- confirming current state;
- adding previously unknown state;
- contradicting accepted state;
- proposing a new event;
- supplying a missing date or explanation;
- duplicating existing evidence;
- unresolved.

Deterministic comparison handles exact structured differences. AI may explain
or classify ambiguity but cannot accept it.

### Event drafting

A candidate change contains a neutral title, evidence-bounded narrative,
affected entities, proposed effective date and basis, before/after state,
supporting and conflicting assertions, missing facts, confidence and review
reason.

### Review

The operator can approve, edit, reject or defer an assertion and event; fix an
entity match; mark evidence as corroborating but not state-changing; link
additional evidence; and split or merge candidates.

Acceptance is transactional: event, state transition, reviewer identity and
audit record commit together.

## User experience

### Organization overview

Show the top-level hierarchy, elected and appointed leadership, department and
major-unit structure, acting/interim/vacant positions, unresolved conflicts
and last verified date by branch.

### Entity detail

Show accepted state, aliases, parent and reporting relationships, occupancy or
membership history, associated events, source assertions and unresolved
candidates.

### Change log

Filter by date, event type, unit, person, certainty and review status. Every
approved entry opens to before/after state and archived evidence.

### Review queue

Show unresolved identities, contradictory assertions, proposed state changes,
proposed events, stale state and extraction failures. Reuse Civic Radar review
conventions while keeping organization actions distinct from issue review.

## Minimal read API

The MVP provides equivalents of:

- GET /api/organizations
- GET /api/organizations/{id}
- GET /api/organizations/{id}/structure?at=YYYY-MM-DD
- GET /api/organizations/{id}/events
- GET /api/units/{id}
- GET /api/positions/{id}
- GET /api/people/{id}
- GET /api/organization-assertions/{id}

Operator mutations may remain server-rendered form actions. A public write API
is not required.

## Authority, confidence and absence

Source authority and extraction confidence are separate. An official directory
is strong evidence of what it displayed on the observation date but may be
weak evidence for an effective date or reason. A signed resolution may
establish both an appointment and its effective date. News may corroborate but
does not replace the primary record.

No numeric score may conceal a material contradiction.

A missing name or unit on a new page is not proof of departure or dissolution.
The system may propose an observed difference but must identify absence as the
observation. Each accepted branch has a last-verified time; stale state is
flagged rather than treated as indefinitely current.

## Auditability and corrections

Record the extracted assertion, model and prompt version, every operator
decision, review edits, prior and replacement entity links, before/after state
and correction history.

Corrections do not erase originals. A corrected event supersedes the earlier
version and explains the correction.

## Security and privacy

Store only public information necessary to identify public officials,
employees, appointees and organizational relationships. Do not collect home
addresses, personal phone numbers, personal email addresses, family
relationships or other sensitive information merely to improve tracking.

The existing LAN/VPN-only deployment constraint remains in force.

## Reliability requirements

The MVP must:

- process asynchronously without blocking normal ingestion;
- be idempotent when a document is processed again;
- preserve deterministic provenance across reprocessing;
- allow retry after prompt or model updates;
- detect duplicate assertions;
- index entity, relationship, time, document and review-status queries;
- make no state change when extraction fails;
- render the current Ventura structure within two seconds at normal
  single-operator load.

## Metrics

Report baseline coverage, positions with accepted occupants, sourced
relationships, stale state, reviewed assertion outcomes, unresolved identities
and contradictions, candidate and approved events, median review time and
precision measured from reviewed samples.

The primary quality measure is the proportion of accepted state and events
traceable to appropriate archived evidence.

## Acceptance criteria

The MVP is complete when:

1. Ventura exists as the root tracked organization.
2. Every current top-level city department is represented.
3. Council, senior leadership, department heads and available board or
   commission rosters have source links.
4. Positions exist independently from their occupants.
5. Parent, reporting, appointing and membership relationships support valid
   time and observation time.
6. At least three source classes are processed automatically, including
   directory pages and council documents.
7. Reprocessing creates no duplicate accepted assertions or events.
8. A changed directory produces a reviewable observed difference rather than
   an unsupported departure claim.
9. An explicit appointment document produces a candidate appointment event
   with effective date and supporting passage.
10. The operator can approve, edit, reject or defer proposals.
11. Approval updates state without deleting history.
12. The UI shows current hierarchy, dated historical snapshot, entity history
    and approved change log.
13. Every accepted relationship and event traces to archived evidence and an
    operator decision.
14. Ambiguous identities cannot be silently auto-merged.
15. Tests cover temporal transitions, duplicate processing, conflicting
    evidence, disappearance from a snapshot and correction history.

## Implementation boundary

Expected placement:

~~~text
core/app/organization_tracker/
    models.py
    schemas.py
    extraction.py
    resolution.py
    reconciliation.py
    events.py
    service.py
    routers.py
    templates/
core/tests/organization_tracker/
cities/ventura/
    organization_sources.py
docs/organization-tracker/
    README.md
    MVP-PRD.md
~~~

This is a logical boundary, not an independently deployed microservice. It may
use Civic Radar's database session, documents, archive references, worker, AI
client and common templates. Other modules should use explicit service
functions or internal events, not modify Organization Tracker tables directly.

## Deferred decisions

After the Ventura baseline demonstrates the model, decide:

- whether organization data stays in each jurisdiction database or moves to a
  shared cross-jurisdiction store;
- whether a message queue is warranted;
- when the module becomes an independently versioned package or service;
- how corporate filings and federal sources enter the source contract;
- whether approved organizational events feed issues, alerts and digests;
- how public presentation and external API authentication should work.
