# Civic Radar Entity Dossiers — MVP PRD

## Status

Proposed.

This document defines an MVP for creating durable, evidence-backed dossiers on people and other entities identified by Civic Radar. A dossier is **not** a second identity system and **not** a free-form biography. It is a normalized, temporal view over Civic Radar's existing `entities` model, enriched with sourced facts, roles, positions, claims, relationships, assessments and derived patterns.

The governing principle is:

> **Compress the presentation, not the evidence.**

The database should preserve the underlying observations, sources, dates and uncertainty. The dossier UI should expose only the most useful current summary unless the user drills down.

---

## 1. Problem

Civic Radar already answers important structural questions: which organizations exist, which positions exist, who occupies them, how reporting lines change and what source assertions support those changes.

The next problem is broader.

Once Civic Radar identifies a consequential person — elected official, appointee, department head, lobbyist, campaign actor, contractor, executive, donor, activist or other civic actor — users need to understand that person's public footprint over time:

- Who are they?
- What roles have they held?
- What policy positions have they taken?
- What factual claims have they made?
- Which organizations, businesses, campaigns and people are they connected to?
- Which connections are direct, which are indirect and which are inferred?
- Have their positions or alliances changed?
- Does rhetoric diverge from voting or governing behavior?
- Are repeated patterns visible across otherwise separate events?
- What does the evidence actually support, and what does it **not** support?

A conventional biography field cannot answer these questions safely or usefully. It collapses time, provenance, degree of confidence and the distinction between observation and interpretation.

The dossier system must preserve those distinctions.

---

## 2. Existing foundation

The Organization Tracker already establishes several architectural rules that the dossier system should inherit rather than fork:

1. `entities` is the shared canonical identity layer.
2. People, organizations, organizational units and positions are all entities.
3. Relationships are temporal.
4. Source assertions are immutable; corrections supersede rather than rewrite history.
5. Current state never destroys history.
6. Extracted AI output does not become accepted state without review.
7. Entity resolution is conservative: failure to resolve is not proof that a new entity exists.
8. Point-in-time queries matter.

The current Organization Tracker's `OrgRelationship` is already a time-bounded edge between two `entities` rows. That is the correct conceptual foundation, but its namespace and vocabulary are organization-specific.

The dossier system therefore should **generalize the existing graph, not create a parallel graph**.

---

## 3. Goals

### MVP goals

1. Create a dossier for any existing `Entity`, initially focusing on `entity_type="person"`.
2. Represent a person's biography as normalized, sourced facts rather than one large prose blob.
3. Represent public roles as temporal relationships to offices, organizations, campaigns and other entities.
4. Represent political, familial, social, business, financial and professional connections as first-class temporal graph edges.
5. Distinguish direct observed relationships from derived/inferred relationships.
6. Represent policy positions independently from factual claims.
7. Represent factual claims independently from analytical assessments.
8. Preserve source provenance and review state for every consequential dossier item.
9. Support point-in-time dossier views.
10. Produce a concise human-readable dossier summary from the normalized records.
11. Make every displayed summary statement drillable to its underlying evidence.
12. Prevent the graph from silently converting an interesting connection into an allegation.

### Non-goals for MVP

- Automated corruption scoring.
- Automated ideological labeling from unsupervised text alone.
- Personality diagnosis.
- Private-person intelligence gathering.
- Inference from private or non-public data.
- Automatic publication of AI-derived allegations.
- Social-network scraping for its own sake.
- A general-purpose knowledge graph unrelated to civic relevance.

---

## 4. Core principle: one canonical entity graph

Civic Radar should have one canonical graph connecting all entities.

Conceptually:

```text
ENTITIES
   │
   ├── people
   ├── organizations
   ├── organizational units
   ├── positions/offices
   ├── companies
   ├── campaigns
   ├── committees/PACs
   ├── agencies
   └── other civic entities
          │
          ▼
ENTITY RELATIONSHIPS
          │
          ├── temporal
          ├── sourced
          ├── typed
          ├── directional
          ├── reviewable
          └── confidence-bearing
          │
          ▼
FACTS / POSITIONS / CLAIMS / EVENTS
          │
          ▼
ASSESSMENTS / DERIVED PATTERNS
          │
          ▼
DOSSIER VIEW
```

The dossier is therefore a **view over the graph and evidence store**, not the source of truth itself.

---

## 5. Relationship graph

### 5.1 Generalize `OrgRelationship`

Introduce a canonical `EntityRelationship` model and migrate the existing organization relationships into it.

The migration should preserve all existing Organization Tracker behavior and IDs where practical. The final system must not maintain duplicate accepted-state edges in both `org_relationships` and `entity_relationships`.

Recommended schema:

```python
class EntityRelationship(Base):
    __tablename__ = "entity_relationships"

    id
    subject_entity_id
    relationship_type
    relationship_subtype
    object_entity_id

    valid_from
    valid_to
    status

    evidence_mode        # explicit | derived | inferred
    confidence           # low | medium | high
    significance         # incidental | relevant | important | defining
    strength             # optional domain-specific text value

    context              # JSONB, e.g. election cycle / organization / topic
    attributes           # JSONB for relationship-specific metadata

    derived_from         # JSONB/list of relationship/assertion IDs where needed

    review_status        # pending | approved | rejected | superseded
    reviewer_note

    created_at
    reviewed_at
```

Do not encode a large relationship vocabulary as a database enum. Continue the repository's current convention of text vocabularies validated in application code.

### 5.2 Canonical direction and inverse display

Store one canonical edge.

Example:

```text
Trump --[endorsed]--> Donalds
```

The UI may render the inverse automatically:

```text
Donalds <--[endorsed_by]-- Trump
```

Do not store both edges.

Maintain an application-level inverse vocabulary:

```python
RELATIONSHIP_INVERSES = {
    "endorsed": "endorsed_by",
    "appointed": "appointed_by",
    "employs": "employed_by",
    "parent_of": "child_of",
    "controls": "controlled_by",
    "donated_to": "received_donation_from",
    # ...
}
```

Symmetric relationships such as `spouse` do not require an inverse label.

### 5.3 Initial relationship taxonomy

Keep the top-level taxonomy restrained.

| Type | Example subtypes |
|---|---|
| familial | spouse, parent, child, sibling, in-law |
| political | ally, rival, endorser, surrogate, mentor, patron |
| organizational | member, officer, employee, board_member, advisor |
| governmental | appointed_by, reports_to, succeeded, predecessor, oversees |
| electoral | candidate_for, campaign_staff, fundraiser, consultant |
| financial | donor, recipient, investor, lender, contractor, beneficiary |
| business | founder, owner, executive, partner, customer, vendor |
| lobbying | lobbyist_for, lobbied_by, client, represented_by |
| professional | colleague, former_colleague, attorney, consultant |
| social | associate, friend, frequent_contact |
| ideological | aligned_with, affiliated_with, supporter |
| adversarial | opponent, litigant, critic, investigated_by |
| educational | attended, taught_at, classmate |
| media | interviewed_by, contributor, host, publisher |

Prefer `type + subtype + attributes` over proliferating hyper-specific edge types.

### 5.4 Observed vs inferred relationships

This distinction is mandatory.

Observed fact:

```yaml
relationship_type: political
relationship_subtype: endorsement
evidence_mode: explicit
confidence: high
```

Derived assessment:

```yaml
relationship_type: political
relationship_subtype: alliance
evidence_mode: inferred
confidence: high
derived_from:
  - endorsement_relationship_id
  - surrogate_activity_assertion_id
  - repeated_public_support_assertion_id
```

"Person A endorsed Person B" and "Person A is a political ally of Person B" are useful but epistemically different statements.

### 5.5 Indirect connections

Indirect paths must never be silently collapsed into direct edges.

Example:

```text
Byron Donalds
    │ spouse
    ▼
Erika Donalds
    │ founder/executive
    ▼
OptimaEd
```

The UI may surface:

> OptimaEd — indirect connection through spouse.

But the database must not silently create:

```text
Byron Donalds --[business_relationship]--> OptimaEd
```

Instead, derived path findings should explicitly preserve the path:

```yaml
source_entity_id: byron_donalds
 target_entity_id: optimaed
finding_type: indirect_connection
path:
  - relationship_byron_erika_spouse
  - relationship_erika_optimaed_executive
hops: 2
direct_relationship: false
confidence: high
```

---

## 6. Dossier object

A dossier identifies an entity as intentionally tracked and stores review/publication metadata, not the entity's substantive facts.

```python
class Dossier(Base):
    __tablename__ = "dossiers"

    id
    entity_id             # unique FK entities.id
    status                # active | watch | archived
    scope                 # local | state | federal | cross_jurisdiction
    importance            # low | medium | high | defining
    publication_status    # internal | review | publishable | published
    review_status         # unreviewed | reviewed | needs_review
    last_reviewed_at
    last_material_change_at
    created_at
    updated_at
```

Creating a dossier must never create a duplicate person entity if the person already exists in `entities`.

---

## 7. Biographical facts

Do not create a giant mutable `PersonProfile` row containing dozens of columns and do not store the entire biography only as prose.

Use atomic facts with evidence and valid time.

```python
class DossierFact(Base):
    __tablename__ = "dossier_facts"

    id
    dossier_id
    fact_category         # identity | education | career | residence | etc.
    fact_key              # birth_date | degree | employer | etc.
    value                 # JSONB

    valid_from
    valid_to
    observed_at

    confidence
    review_status
    source_assertion_id
    superseded_fact_id
    created_at
```

Examples:

```yaml
fact_category: education
fact_key: degree
value:
  institution: Florida State University
  degree: BS
  fields: [finance, marketing]
  year: 2002
```

Employment or public office that connects the subject to another identifiable entity should normally be modeled as a relationship rather than duplicated as a fact.

---

## 8. Roles

Roles are temporal relationships.

Examples:

```yaml
subject: Byron Donalds
relationship_type: governmental
relationship_subtype: occupies_position
object: U.S. Representative, Florida 19th District
valid_from: 2021-01-03
valid_to: null
```

```yaml
subject: Byron Donalds
relationship_type: electoral
relationship_subtype: candidate_for
object: Governor of Florida
context:
  cycle: 2026
  party: Republican
status: active
```

If the candidate wins, do not overwrite `candidate_for`. Close or update the electoral state as appropriate and create the new office-occupancy relationship.

History remains queryable.

---

## 9. Policy positions

A political position is not a factual claim and should not be stored as one.

```python
class DossierPosition(Base):
    __tablename__ = "dossier_positions"

    id
    dossier_id
    topic
    stance
    strength              # weak | moderate | strong | defining
    scope                 # municipal | county | state | federal | unspecified
    components            # JSONB/list
    qualifiers            # JSONB/list

    valid_from
    valid_to
    observed_at

    evidence_mode
    confidence
    review_status
    source_assertion_id
    superseded_position_id
    created_at
```

Example:

```yaml
topic: firearms
stance: expand_or_preserve_access
strength: very_strong
components:
  - oppose_universal_background_checks
  - oppose_red_flag_laws
confidence: high
```

Use `mixed` or structured components when the record is genuinely mixed. Do not force every position onto a one-dimensional ideological scale.

---

## 10. Issue salience

Two people may hold nominally similar positions while assigning radically different importance to them.

Track salience separately.

```python
class DossierIssueSalience(Base):
    __tablename__ = "dossier_issue_salience"

    id
    dossier_id
    topic
    salience              # low | medium | high | defining
    basis                 # JSONB/list of position, speech, vote, campaign IDs
    confidence
    valid_from
    valid_to
    review_status
```

Avoid pseudo-precision such as `0.927` unless an actual quantitative methodology exists.

---

## 11. Claims

Claims are atomic propositions made by the dossier subject or formally attributed to them.

```python
class DossierClaim(Base):
    __tablename__ = "dossier_claims"

    id
    dossier_id
    speaker_entity_id

    made_at
    topic
    proposition
    claim_type

    verification_status   # unverified | supported | contradicted | mixed | normative | disputed
    evidence_strength     # weak | medium | strong
    significance          # low | medium | high

    source_assertion_id
    verification_notes
    review_status
    created_at
```

Initial `claim_type` vocabulary:

- factual
- causal
- historical
- historical_causal
- quantitative
- prediction
- policy_argument
- normative
- rhetorical

This prevents the system from fact-checking value judgments as though they were empirical propositions.

---

## 12. Assessments

Analytical judgments must never be stored as though they were observed biographical facts.

```python
class DossierAssessment(Base):
    __tablename__ = "dossier_assessments"

    id
    dossier_id
    dimension
    assessment
    confidence
    basis                 # IDs of claims/events/relationships/positions
    method                 # human | rule_based | model_assisted
    review_status
    reviewer_note
    valid_from
    valid_to
    created_at
```

Example:

```yaml
dimension: argumentative_consistency
assessment: frequent_category_slippage
confidence: medium
basis:
  - claim_123
  - event_456
method: human
```

The system should comfortably store:

- "Claim X was contradicted by evidence."
- "Several claims display a repeated reasoning pattern."

It should not store unsupported insults, amateur diagnoses or subjective intelligence labels as dossier facts.

---

## 13. Derived patterns

Patterns are higher-order findings derived from multiple underlying records.

```python
class DossierPattern(Base):
    __tablename__ = "dossier_patterns"

    id
    dossier_id
    pattern_type
    title
    description
    first_observed
    last_observed
    occurrence_count
    confidence
    basis                # JSONB/list of record IDs
    review_status
    created_at
    updated_at
```

Examples:

- policy reversal
- ally_to_critic
- donor_to_appointee
- repeated_claim_contradiction
- rhetoric_vote_divergence
- conclusion_first_reasoning
- recurring_vendor_network

No pattern should become publishable solely because an LLM generated it. Model-generated patterns enter `pending` review.

---

## 14. Connection findings

Graph structure can reveal combinations worth human attention without proving wrongdoing.

Create a dedicated finding object rather than converting structural coincidence into a relationship assertion.

```python
class ConnectionFinding(Base):
    __tablename__ = "connection_findings"

    id
    dossier_id
    finding_type
    description
    involved_entity_ids
    relationship_path_ids
    significance
    confidence
    interpretation
    not_claimed           # JSONB/list
    review_status
    created_at
```

Example:

```yaml
finding_type: overlapping_political_business_network
description: >
  Multiple direct and indirect relationships connect the subject's
  political network with entities active in a policy area promoted by
  the subject.
interpretation: potential_policy_relevance
not_claimed:
  - corruption
  - quid_pro_quo
  - illegal_conduct
confidence: medium
```

`not_claimed` is intentionally explicit. Civic Radar should preserve the line between "this deserves examination" and "this proves misconduct."

---

## 15. Evidence model

Every consequential dossier item must be traceable to evidence.

Where possible, generalize the Organization Tracker's immutable source-assertion pattern rather than inventing dossier-only provenance semantics.

Long term, `OrgSourceAssertion` should evolve into or feed a generic `EntityAssertion` layer that can support both organization tracking and dossiers.

Minimum evidence record requirements:

- source/document ID
- source URL or archived artifact
- quoted passage or location reference where permitted
- page/section/timestamp
- observed date
- effective date when different
- extraction method
- model/prompt version when model-derived
- evidence mode: `explicit | derived | inferred`
- source authority
- confidence
- review status
- supersession chain

Corrections must create a replacement/superseding record rather than rewriting the historical assertion.

---

## 16. Temporal semantics

Dossiers must support both observed time and valid/effective time.

Examples:

- A source is observed on August 29 but says an appointment became effective August 15.
- A friendship is reported years after it began.
- A candidate changes an abortion position during a campaign.
- An alliance ends without a precise public date.

Use:

- `observed_at`: when Civic Radar learned it.
- `valid_from`: when the state is believed to have begun.
- `valid_to`: when it ended.

Unknown dates remain unknown. Do not manufacture precision.

Point-in-time dossier queries should answer:

> What did Civic Radar's accepted evidence indicate about this person on date X?

---

## 17. Relationship significance and strength

Do not equate existence with importance.

A single interview and a decade-long political alliance are both graph edges but should not present equivalently.

Use restrained categorical values.

`significance`:

- incidental
- relevant
- important
- defining

`strength` may be relationship-specific and should not pretend to be a universal numeric measurement.

Examples:

- political alliance: weak / moderate / strong / very_strong
- ownership: minority / controlling / wholly_owned
- donation: amount may live in `attributes`
- family relationship: strength usually unnecessary

---

## 18. Dossier summary

The user-facing dossier should be generated from normalized accepted records, not maintained manually as the authoritative record.

Example compact view:

```text
Byron Donalds — Republican, Florida

U.S. representative (FL-19), 2021–present; 2026 Republican nominee for
Florida governor. Former Florida legislator and financial-services
professional. Strongly Trump-aligned and associated with the House Freedom
Caucus. Defining issues include immigration enforcement, school choice,
tax reduction, gun rights and socially conservative policy. Market-oriented
on healthcare and strongly supportive of cryptocurrency and emerging
technology. Legislative record includes successful bipartisan work in
selected regulatory and fisheries matters. Recent public-health and
historical claims have drawn factual criticism. Analytical record indicates
repeated conclusion-first reasoning and category slippage in ideologically
salient arguments; confidence in that assessment remains medium pending
additional observations.
```

Each sentence must be generated from and linked to the underlying records.

The summary is disposable. The evidence graph is authoritative.

---

## 19. Dossier UI

### `/dossiers`

List tracked dossiers with:

- entity name
- entity type
- current principal role
- jurisdiction
- status
- last material change
- pending-review count
- importance

### `/dossiers/{id}`

Default compact dossier:

1. identity/current role
2. concise generated summary
3. major current positions
4. defining issue salience
5. key connections
6. notable recent claims
7. recent changes
8. analytical findings/patterns
9. evidence/review warnings

### Tabs or drill-down panels

- Timeline
- Roles
- Positions
- Claims
- Connections
- Organizations
- Money
- Sources
- Assessments
- Change history

### Connection graph

Graph rendering must differentiate:

- direct vs indirect
- observed vs inferred
- active vs historical
- strength/significance
- approved vs pending

Clicking an edge opens:

- exact relationship
- valid dates
- evidence
- source assertions
- confidence
- whether it is observed or derived
- any inverse rendering

---

## 20. Review workflow

Nothing model-inferred should silently enter accepted dossier state.

Recommended pipeline:

```text
source/document
   ↓
extract candidate assertions
   ↓
resolve entities
   ↓
classify proposition
   ↓
reconcile against accepted state
   ↓
propose fact / relationship / position / claim / pattern
   ↓
human review
   ↓
accepted state
   ↓
dossier summary / alerts
```

Review actions:

- approve
- edit + approve
- reject
- defer
- merge with existing
- mark uncertain

Acceptance should be transactional: accepted record and review state commit together.

---

## 21. Change detection

A dossier is valuable because it changes.

Material-change detection should eventually support:

- new role
- role ended
- new organization affiliation
- new business relationship
- new donor/recipient relationship
- alliance formed
- alliance weakened/ended
- endorsement
- policy position changed
- factual claim contradicted
- repeated claim despite correction
- new conflict-relevant indirect path
- rhetoric/vote divergence
- assessment confidence changed

A dossier's `last_material_change_at` should advance only when a reviewed accepted change is material, not whenever a source merely repeats known information.

---

## 22. Queries the model must support

MVP architecture should make these queries possible even if every UI is not built immediately:

- Who is this person connected to?
- Which connections are direct?
- Which are inferred?
- What did this network look like six months ago?
- Who moved from ally to critic?
- Which donors later received appointments?
- Which contractors are connected to officials overseeing procurement?
- Who worked together before appearing together in government?
- Which actors share donors, consultants, boards or advocacy groups?
- Which relationships appeared shortly before a policy decision?
- Which policy positions have changed?
- Which claims have been contradicted?
- Which claims were repeated after contradiction?
- Does rhetoric diverge from votes or governing actions?
- Which issues trigger unusually low-quality factual claims?
- What evidence supports this analytical pattern?

---

## 23. Guardrails

### 23.1 No guilt by graph

A graph path is not proof of influence, coordination or wrongdoing.

The system should phrase structural findings as:

> A is connected to C through B.

not:

> A controls C.

unless the evidence specifically supports control.

### 23.2 No relationship inflation

Repeated co-appearance does not automatically mean friendship.

Use conservative labels such as `associate` until stronger evidence exists.

### 23.3 No direct-edge fabrication

A two-hop family/business connection remains a two-hop connection.

### 23.4 No analytical laundering

An AI-generated assessment cannot become a factual biography field merely because the wording sounds confident.

### 23.5 Public-interest scope

The feature is intended to track civic relevance. Do not create expansive dossiers on private individuals merely because they are connected socially to a public figure.

### 23.6 Source hierarchy

Prefer:

1. official records
2. primary statements/transcripts
3. court/financial/campaign filings
4. high-quality reporting
5. secondary summaries
6. weak/social sources only as leads pending corroboration

---

## 24. Migration strategy

### Phase 0 — preserve the working Organization Tracker

Before changing schema, add regression tests covering all existing organization relationship behavior:

- `occupies_position`
- `reports_to_position`
- `appoints`
- point-in-time queries
- succession
- approval applying accepted state
- inverse entity detail history

### Phase 1 — canonical entity relationship graph

1. Add `EntityRelationship`.
2. Add relationship vocabulary/inverse helpers.
3. Migrate existing `org_relationships` rows.
4. Switch Organization Tracker services and queries to the canonical table.
5. Verify current Organization Tracker dashboard is unchanged.
6. Remove or formally deprecate `OrgRelationship` once no runtime reads/writes remain.

There must not be two independently writable accepted relationship graphs.

### Phase 2 — dossier core

Add:

- `Dossier`
- `DossierFact`
- `DossierPosition`
- `DossierIssueSalience`
- `DossierClaim`

Add basic CRUD/service functions and point-in-time read queries.

### Phase 3 — evidence and review

Generalize or bridge source assertions so dossier records are evidence-backed and reviewable.

Add dossier review UI.

### Phase 4 — connections

Add:

- relationship exploration UI
- direct/indirect distinction
- graph-path derivation
- `ConnectionFinding`

### Phase 5 — assessments and patterns

Add:

- `DossierAssessment`
- `DossierPattern`
- human-reviewed model-assisted pattern proposal

### Phase 6 — generated compact dossier

Generate a concise normalized summary from approved records, with sentence-level provenance links.

---

## 25. Suggested module layout

```text
core/app/dossiers/
    __init__.py
    models.py
    service.py
    routers.py
    resolution.py
    extraction.py
    reconciliation.py
    relationship_types.py
    graph.py
    summarization.py
    review.py

core/tests/dossiers/
    test_models.py
    test_relationships.py
    test_temporal_queries.py
    test_indirect_connections.py
    test_claims.py
    test_positions.py
    test_assessments.py
    test_review.py
    test_summary.py
```

The canonical generic relationship model may ultimately belong outside the `dossiers` namespace (for example `app/entity_graph/`) because Organization Tracker and dossiers both depend upon it.

Preferred eventual layout:

```text
core/app/entity_graph/
    models.py
    service.py
    relationship_types.py
    queries.py

core/app/organization_tracker/
    ...

core/app/dossiers/
    ...
```

---

## 26. Acceptance criteria

The MVP is successful when all of the following are true:

1. An existing Person entity can be promoted to a tracked dossier without duplicating identity.
2. A dossier can show a point-in-time role history.
3. Political, familial, business and organizational relationships can be stored with provenance and dates.
4. The same relationship edge is not duplicated merely to support inverse display.
5. An indirect spouse → company connection remains explicitly indirect.
6. A policy position can change over time without deleting the old position.
7. A claim can be marked contradicted without turning a policy disagreement into a fact-check.
8. An assessment can cite multiple underlying claims/events without becoming a biographical fact.
9. Model-generated inferred relationships and patterns remain pending until reviewed.
10. The UI can produce a compact dossier summary while retaining drill-down access to all evidence.
11. Existing Organization Tracker relationship behavior and point-in-time views remain correct after graph generalization.
12. Civic Radar can answer "why do we believe this?" for every consequential dossier statement.

---

## 27. Example: normalized person dossier

A fully populated person dossier might conceptually contain:

```yaml
entity:
  canonical_name: Byron Donalds
  entity_type: person

facts:
  - category: education
    key: degree
    value:
      institution: Florida State University
      degree: BS
      fields: [finance, marketing]
      year: 2002

roles:
  - relationship: occupies_position
    object: U.S. Representative — Florida 19th District
    valid_from: 2021

  - relationship: candidate_for
    object: Governor of Florida
    context:
      cycle: 2026
      party: Republican

positions:
  - topic: immigration
    stance: restrictive
    strength: defining

  - topic: firearms
    stance: expand_or_preserve_access
    strength: very_strong

connections:
  - target: Donald Trump
    type: political
    subtype: alliance
    evidence_mode: inferred
    confidence: high

  - target: Erika Donalds
    type: familial
    subtype: spouse
    evidence_mode: explicit
    confidence: high

claims:
  - topic: measles
    claim_type: causal
    verification_status: contradicted

assessments:
  - dimension: argumentative_consistency
    assessment: frequent_category_slippage
    confidence: medium

patterns:
  - type: epistemic
    title: conclusion-first reasoning
    confidence: medium
```

The compact dossier may summarize this in approximately 100–150 words, but none of the underlying normalization or evidence is discarded.

---

## 28. Architectural conclusion

Civic Radar began by tracking public institutions as structures. Dossiers extend that model to the people and networks operating within and around those structures.

The resulting system should not think of an institution as merely a list of officials, nor a person as merely a biography.

Public institutions are networks of:

- people
- positions
- organizations
- authority
- money
- claims
- policy choices
- affiliations
- relationships

all changing through time.

The dossier is the readable projection of that network around one entity.

The graph and evidence remain the truth underneath it.
