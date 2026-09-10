# Litigation Source Ingestion

**Status:** Proposed  
**Initial deployment:** City of San Buenaventura (City of Ventura)  
**Tracks:** [Issue #5](https://github.com/quistuipater/civic-radar/issues/5)  
**Related:** [PR #4](https://github.com/quistuipater/civic-radar/pull/4)

## Purpose

Civic Radar currently learns about litigation when it appears in an already
monitored government record, such as a council agenda or an outside-counsel
contract. That is useful evidence, but it is not a court-record discovery
system. A case can be filed, appealed, dismissed or decided without producing
a city agenda item.

This design adds court opinions and available docket material to the existing
archive-first pipeline. It does not create a parallel litigation tracker. The
structured fields proposed in PR #4 remain attributes of the existing
`Issue`, which is already the system's durable representation of a civic matter
tracked over time.

## Governing principles

1. **Discovery is not verification.** A third-party search hit is a candidate.
   The acquired opinion, docket or filing and its court identifiers are the
   evidence.
2. **Archive before interpretation.** Search responses and acquired artifacts
   are hashed and archived before parsing, classification or matching.
3. **Party status must be established.** A textual reference to Ventura does
   not establish that the city is a party.
4. **Coverage must be stated.** RECAP is contributed, not complete. California
   trial-court access is decentralized and not available as a complete free
   feed.
5. **Human review controls linkage.** An exact, normalized case-number match
   may propose an Issue link. It does not silently create or accept one.

## Source assessment

| Source | Role | Automation | Principal limitation |
| --- | --- | --- | --- |
| [CourtListener Search API](https://www.courtlistener.com/help/api/rest/) | Primary machine-readable discovery for opinions and federal cases | Supported REST API | Authentication and rate limits; search results still require party validation |
| [RECAP](https://www.courtlistener.com/recap/) | Federal dockets and PACER documents contributed to the public archive | CourtListener search and PACER-data APIs | Incomplete by design; absence is not evidence |
| [California Published/Citable Opinions](https://courts.ca.gov/opinions/publishedcitable-opinions) | Authoritative California opinion text and publication status | Verification/acquisition where a stable court URL exists | Appellate opinions, not the trial-court universe |
| [California Appellate Case Information](https://appellatecases.courtinfo.ca.gov/search.cfm?dist=0) | Authoritative appellate docket, party and originating-case metadata | Operator verification initially | Interactive search; no supported public bulk API |
| [Ninth Circuit Opinions](https://www.ca9.uscourts.gov/opinions/) | Authoritative federal appellate opinions | Verification/acquisition | Appellate opinions only |
| [GovInfo USCOURTS](https://www.govinfo.gov/app/collection/USCOURTS) | Official federal opinions with metadata and bulk/API access | Secondary automated verification | Participating-court opinion collection, not a complete docket system |
| [Ventura Superior Court Public Access](https://ventura.ecourt.com/public-portal/) | Local trial-court case index and available documents | Operator-assisted import only | Account required; no supported public API or bulk feed; some records/documents restricted or chargeable |

Google Scholar, Justia and FindLaw may help an operator cross-check a case, but
they are not ingestion contracts. The system must not scrape them.

## Discovery contract

CourtListener is the initial automated discovery provider. Its connector must
be jurisdiction-independent. Ventura-specific aliases belong in city source
configuration.

Run separate narrow queries because CourtListener recommends avoiding long OR
expressions. Begin with:

```text
caseName:"City of San Buenaventura"
caseName:"City of Ventura"
```

Federal docket searches must use the equivalent party/caption fields rather
than unrestricted full-text queries. Agency expansion begins with:

```text
"Ventura Police Department"
"Ventura Water"
```

Each configured alias has an explicit match mode:

- `caption_exact`: normalized caption contains the complete alias;
- `party_exact`: provider party data contains the complete alias;
- `text_candidate`: alias occurs only in document text and always requires
  review before the record is treated as involving the city.

The provider response is not sufficient by itself. When a result supplies an
official court download URL, acquire and archive that representation. Otherwise
archive the CourtListener-hosted opinion or RECAP document and retain its
provenance and upstream identifiers.

## Source configuration

The existing `Source` registry remains the scheduling and health boundary. A
Ventura entry should use:

```python
dict(
    name="CourtListener — City of Ventura litigation",
    jurisdiction="City of Ventura",
    agency="City Attorney",
    body=None,
    source_type="court_record_search",
    authority_level="secondary_discovery",
    url="https://www.courtlistener.com/api/rest/v4/search/",
    fetch_method="courtlistener_search",
    connector="none",
    polling_interval_minutes=1440,
    parser_type="court_record",
    known_limitations=(
        "CourtListener and RECAP coverage is incomplete. Search hits are "
        "candidates until party status is validated against the record."
    ),
)
```

The token, if used, is read from `COURTLISTENER_API_TOKEN`. It must not appear
in seed data, logs, request archives or generated metadata.

## Archived representation

Every result must preserve enough source metadata to reproduce and audit the
match:

- provider and provider object type;
- provider cluster, docket, opinion or document ID;
- case name and full caption when available;
- docket number and court identifier/name;
- filed date and publication status;
- query alias and match mode that discovered it;
- CourtListener result URL;
- official court URL when supplied;
- original download URL and acquisition timestamp;
- content hash, MIME type and local archive path;
- provider coverage warning.

Use provider object ID as the stable external identity and content hash as the
representation identity. A corrected opinion may therefore update an existing
provider object while adding a new immutable archived representation.

If the record-provenance ontology in PR #2 is merged, map the court filing or
opinion to `PublicRecord` and each acquired PDF/HTML/JSON copy to a
`RecordRepresentation`. Until then, keep the metadata in the existing archive
sidecar without inventing a competing provenance model.

## Pipeline

1. The worker selects the due `courtlistener_search` source.
2. The connector executes each configured alias as a separate request and
   archives every raw JSON response page.
3. It normalizes results and rejects obvious text-only false positives from
   automatic party treatment.
4. New or changed artifacts are downloaded and archived.
5. A `Document` is created with `document_type` such as `court_opinion`,
   `court_order`, `court_filing` or `docket_snapshot`.
6. Existing parsing and classification run without a separate AI pipeline.
7. Case-number matching proposes a link to a litigation Issue. Name-only and
   text-only matches enter human review.
8. Accepted links add evidence to the Issue timeline; they do not overwrite
   city agenda records or prior court representations.

Historical backfill is a separate command with bounded date ranges and a
resume cursor. Routine polling only requests recent results so a backfill
cannot exhaust the provider allowance or delay normal ingestion.

CourtListener recommends alerts/webhooks instead of frequent polling. Civic
Radar's Ventura deployment is LAN/VPN-only, so the MVP uses conservative daily
polling. A webhook must not be introduced until Civic Radar has an explicitly
authorized public receiver and replay protection.

## Matching and review rules

The match hierarchy is:

1. accepted provider ID already associated with an Issue;
2. exact normalized court plus case number;
3. exact case number with a court conflict, requiring review;
4. exact party/caption alias with no case-number match, requiring review;
5. full-text mention only, retained as a candidate and never auto-linked.

No case status may be inferred from silence or the age of the last record.
Disposition values such as `settled`, `dismissed`, `judgment` or `on_appeal`
require an explicit court record or other appropriate primary evidence.

## Ventura Superior Court gap

The local portal requires an account and does not advertise a supported public
API or bulk feed. Civic Radar must not automate browser login, evade access
controls or imply that a CourtListener search covers all local cases.

The MVP provides an operator-assisted path using the existing manual-document
submission flow. The operator supplies the case number, court, case caption,
record date, original portal URL and legally acquired file. The archive
metadata records that acquisition was manual and whether the submitted copy is
known to be complete.

A later browser-assisted workflow requires separate authorization and must
still respect document charges, restricted cases, CAPTCHA and terms of access.

## Failure handling

- HTTP 401/403 records a failed fetch and reports missing/invalid credentials;
- HTTP 429 honors `Retry-After`, records throttling and leaves the cursor
  unchanged;
- malformed provider data archives the response and fails that result without
  blocking other aliases;
- download failure retains the discovery record but creates no parsed
  `Document` pretending the artifact was acquired;
- a provider result disappearing does not delete its archived evidence or
  change case status;
- reprocessing the same provider ID and content hash is idempotent.

## Test plan

All tests use fixtures; none call a live court service.

- exact-caption discovery for both city names;
- unrelated opinion containing a textual Ventura reference;
- published and unpublished status selection;
- CourtListener opinion with an official California PDF URL;
- RECAP docket with no contributed document;
- corrected opinion with the same provider ID and a new content hash;
- duplicate polling run;
- exact case-number Issue-link candidate;
- ambiguous name-only match routed to review;
- 401, 429, malformed JSON and partial download failure;
- cursor preservation after failure;
- token redaction from logs and archive metadata;
- manual Ventura Superior Court submission metadata.

## Delivery boundary

The first implementation PR should include the CourtListener connector,
Ventura source configuration, archive metadata, fixtures, idempotency and
failure tests. It should not attempt to scrape the Ventura Superior Court
portal, auto-create Issues, accept name-only links, reconstruct a complete
historical docket or duplicate PR #4's litigation fields.

