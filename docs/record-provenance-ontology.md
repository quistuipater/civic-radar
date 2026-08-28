# Public-record provenance ontology

## Why this exists

Civic Radar previously treated an archived `Document` as though it were the public record itself. That assumption fails when a filing office or publication system exposes a redacted, transformed or otherwise incomplete copy of an underlying record.

The triggering case was a Ventura County campaign-finance filing published through NetFile. The online PDF redacted information from an official County receipt stamp, including material that appears to be ordinary public institutional information. Ventura County's Public Information Officer explained that NetFile automatically redacts electronically submitted campaign documents, while the County redacts paper submissions before posting them online. Under the FPPC rules cited by the County, campaign reports remain public records and unredacted copies are available for inspection or reproduction even when the online publication is redacted.

The resulting rule for Civic Radar is simple:

> A retrieved artifact is evidence about a public record. It is not necessarily the public record itself.

## Core objects

### PublicRecord

The underlying filed, issued or maintained record as a legal or administrative object.

A `PublicRecord` exists independently of any particular URL, PDF, API response, scan or copy. It can have multiple representations over time and through different access channels.

Important attributes include:

- record type and identifier;
- jurisdiction and agency;
- record date;
- legal access status;
- governing access basis;
- whether an unredacted form is available;
- how an unredacted form may be obtained.

### RecordRepresentation

A specific representation of a `PublicRecord` that Civic Radar acquires and archives as a `Document`.

Examples include:

- redacted public web PDF;
- API rendering;
- filed original;
- clerk-provided copy;
- scanned paper record;
- copy received by email;
- copy obtained at a public counter.

A representation records its completeness, redaction status, redaction authority and method, retrieval method and any access constraints encountered.

### RecordRepresentationGap

A known loss, suppression or difference in a representation.

Examples include:

- an explicitly blacked-out field;
- a field omitted from an API response;
- a truncated attachment;
- information lost in a transformation;
- collateral removal caused by a fixed automated redaction mask.

A gap is provenance, not merely missing data. It answers the question: "Why is this value not visible in this representation?"

## Critical reasoning rule

Civic Radar must distinguish these states:

1. The underlying public record affirmatively contains no value.
2. A representation contains no value and is known to be complete.
3. A representation is incomplete, redacted or transformed and the underlying value is unknown.
4. A specific value is known to have been removed from the representation.

Only states 1 and, with suitable evidence, 2 may support an inference from absence. States 3 and 4 must not be treated as evidence that a fact was absent from the underlying record.

This rule applies particularly to Organization Tracker reconciliation. A missing name, title, unit or relationship in a redacted representation cannot support a departure, vacancy, abolition or other state-change candidate unless independent evidence establishes the absence in the underlying record.

## Relationship to Document

`Document` remains Civic Radar's immutable archived artifact: the bytes actually retrieved and hashed.

The ontology now separates that artifact from the public record it represents:

`PublicRecord -> RecordRepresentation -> Document`

A public record may therefore have several archived Documents, each carrying different evidentiary value.

Example:

- PublicRecord: Re-Elect Fryhoff for Sheriff 2028, FPPC Form 410, filed 2026-08-18
  - Representation A: NetFile public PDF, redacted, retrieved via public API
  - Representation B: unredacted copy supplied by filing officer

The two Documents are not duplicates merely because they refer to the same filing. Their differences are themselves evidence about publication and access policy.

## Redaction semantics

Redaction vocabulary should describe what is observed without overstating motive.

Recommended `gap_type` values:

- `redaction`
- `omission`
- `truncation`
- `unavailable_attachment`
- `transformation_loss`
- `unknown`

Recommended `cause` values:

- `privacy`
- `statutory`
- `filing_officer_policy`
- `vendor_automation`
- `collateral`
- `unknown`

Recommended `verification_status` values:

- `observed` — the gap is visible in the acquired representation;
- `inferred` — the gap is strongly suggested but not independently confirmed;
- `confirmed` — comparison with a more complete representation or authoritative statement establishes what happened.

A cause should remain `unknown` unless supported. In particular, automated masking that removes public institutional text should be recorded as `collateral` only when the evidence supports that interpretation.

## Access semantics

The ontology separates legal availability from practical accessibility.

A record may be legally public while its available representations impose different access costs. Examples include:

- immediate anonymous web access;
- API access;
- email request;
- records request;
- appointment;
- in-person inspection;
- copying fee;
- mailing delay.

`access_constraints` records what Civic Radar actually encounters. It does not by itself assert that a constraint is lawful or unlawful.

This distinction provides the foundation for measuring transparency friction separately from the legal status of a record.

## Implementation rules

1. Do not create a `PublicRecord` for every ordinary web page automatically. Create one when the source is meaningfully a filed, issued or maintained public record or when multiple representations need to be reconciled.
2. A `RecordRepresentation` must point to an immutable archived `Document`.
3. When a source is known to publish redacted copies, record representation completeness even if no individual redaction has yet been classified.
4. Record individual gaps when they affect extraction, interpretation, comparison or transparency analysis.
5. Prefer `unknown` over assumptions about why information is missing.
6. Acquisition of a more complete representation adds evidence; it does not overwrite or delete the earlier representation.
7. Differences between representations are auditable facts and should remain historically queryable.

## Future integration

The first implementation establishes the ontology and database tables. Follow-on work should:

- expose representation metadata through document APIs;
- allow operators to associate multiple Documents with one PublicRecord;
- surface completeness/redaction warnings in document and Organization Tracker review screens;
- prevent absence-based reconciliation when the source representation is incomplete;
- compare redacted and unredacted representations when both are available;
- capture retrieval timings and access steps for transparency-friction measurement.
