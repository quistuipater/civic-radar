> **FORK NOTE (Santa Cruz Civic Radar):** This document was written for
> Ventura Civic Radar and inherited as-is when this repo was forked for
> Santa Cruz, CA. The architecture below (schema, pipeline shape, AI
> guardrails, phase structure) is city-agnostic and still applies. Anything
> that names specific Ventura agencies, geography, or sources (e.g. "Ventura
> County Board of Supervisors," "RMA," specific §13.1 source URLs) is stale
> and should be re-derived for Santa Cruz via real source research (see
> README.md's TODO section) rather than treated as a requirement for this
> fork. Nothing below has been edited for Santa Cruz yet.

# Product Requirements Document

# Ventura Civic Radar

## Local AI System for Tracking Ventura County Political and Civic Issues

Version: 0.1
Owner: Mark Gibbs
Primary deployment target: `madhatter` local server/workstation
Primary use case: Track, classify, summarize, and alert on Ventura County and City of Ventura political, planning, land-use, regulatory, election, and civic-governance issues.

---

## 1. Executive Summary

Ventura Civic Radar is a local-first civic intelligence system designed to monitor official public sources, civic documents, public meeting agendas, staff reports, notices, campaign filings, local news, and selected social/community signals related to Ventura County politics and governance.

The system’s purpose is not simply to collect news. Its purpose is to identify issues early, track their lifecycle, preserve original source material, summarize what changed, detect deadlines and votes, and help residents understand when and how they can act.

The system should treat local politics as a structured stream of issue-events. Every meeting agenda item, public notice, staff report, ordinance amendment, candidate filing, campaign-finance update, public comment, planning application, or media story should be captured as evidence and attached to one or more tracked issues.

The system should run primarily on `madhatter` using local AI models where practical. Cloud AI may optionally be used as an escalation path for unusually complex or high-stakes analysis, but the core product should not depend on cloud inference.

---

## 2. Product Goals

The product exists to answer five practical questions:

1. What changed in Ventura civic and political affairs since the last review?
2. Which issues are moving toward a vote, hearing, deadline, or public-comment window?
3. Which items are politically, legally, financially, or neighborhood-significant?
4. What are the source documents, who are the decision-makers, and what is the timeline?
5. What should a resident, journalist, columnist, neighborhood group, or civic watchdog know now?

The system should produce concise, verifiable, source-linked civic intelligence rather than general commentary.

---

## 3. Non-Goals

The system is not intended to:

1. Replace legal advice.
2. Replace expert land-use, CEQA, campaign-finance, or municipal-law analysis.
3. Automatically publish accusatory or reputationally risky claims.
4. Treat Nextdoor, Facebook, X, or community chatter as authoritative.
5. Make autonomous political judgments without review.
6. Provide real-time meeting transcription in the first release.
7. Track every city and agency in Ventura County from day one.
8. Become a general-purpose local news website in the first release.

---

## 4. Core Product Principle

Archive first. Interpret second. Publish third.

The system must preserve raw evidence before producing summaries or alerts. Local-government records can change, links can disappear, agendas can be revised, supplemental packets can be added late, and public notices can be hard to find later. The archive is the foundation.

The AI layer should be treated as an analytical assistant, not the system of record.

---

## 5. Target Users

### 5.1 Primary User

The primary user is Mark Gibbs acting as a columnist, analyst, consultant, civic observer, and system operator.

Primary needs:

1. Find important civic issues early.
2. Understand staff reports and agenda items quickly.
3. Detect procedural changes that affect transparency.
4. Track the lifecycle of issues across meetings and agencies.
5. Produce accurate summaries and commentary with original-source support.
6. Avoid being misled by overheated social posts or official euphemisms.

### 5.2 Secondary Users

Possible secondary users include:

1. Ventura residents.
2. Neighborhood groups.
3. Local journalists.
4. Civic watchdogs.
5. Candidate or campaign observers.
6. Small local advocacy groups.
7. Policy researchers.
8. Legal or planning professionals needing situational awareness.

### 5.3 User Personas

#### Civic Analyst

Wants to know which issues are moving and why they matter. Needs timelines, source documents, and summaries.

#### Neighborhood Resident

Wants to know whether a nearby project, zoning change, ordinance amendment, rate increase, or public hearing affects them.

#### Local Watchdog

Wants to detect reduced transparency, procedural changes, late supplemental packets, compressed notice windows, and unusual agenda handling.

#### Political Observer

Wants to track campaign finance, candidate filings, endorsements, elected officials, votes, appointments, and district-level issues.

---

## 6. Scope

### 6.1 Phase 1 Scope

Phase 1 should focus on the City of Ventura and selected county-level sources.

Included:

1. City of Ventura City Council agendas.
2. City of Ventura Planning Commission agendas.
3. City of Ventura public notices.
4. City of Ventura staff reports, ordinances, resolutions, agenda packets, supplemental packets.
5. Ventura County Board of Supervisors agendas.
6. Ventura County Planning Commission agendas.
7. Ventura County Resource Management Agency planning notices.
8. Ventura County Elections candidate and campaign pages.
9. NetFile campaign-finance filings for Ventura County.
10. Local media and newsletters where accessible.
11. Manually submitted Nextdoor/social screenshots or pasted posts.

### 6.2 Phase 2 Scope

Phase 2 may add:

1. Other Ventura County cities.
2. School boards.
3. Water districts.
4. Sanitation districts.
5. Transportation agencies.
6. LAFCo.
7. Coastal Commission items affecting Ventura County.
8. FPPC enforcement and advice letters.
9. Court dockets where relevant and legally accessible.
10. Meeting video and transcript ingestion.

### 6.3 Phase 3 Scope

Phase 3 may add:

1. Public-facing subscription alerts.
2. Resident-personalized geography alerts.
3. Interactive maps.
4. FOIA/PRA request tracking.
5. Automated public-comment drafting assistance.
6. Cross-county comparison of notice practices.
7. Candidate and donor network analysis.
8. Public website or newsletter publishing workflow.

---

## 7. System Overview

The system consists of the following major components:

1. Source registry.
2. Scheduled ingestion.
3. Raw archive.
4. Document parsing.
5. Structured extraction.
6. AI classification and summarization.
7. Issue clustering.
8. Deadline and event detection.
9. Human review queue.
10. Dashboard.
11. Alerting system.
12. Publishing/export system.
13. Monitoring and observability.

Recommended first implementation stack:

1. Debian on `madhatter`.
2. Docker Compose.
3. PostgreSQL.
4. pgvector.
5. n8n.
6. Python workers.
7. Ollama or llama.cpp-compatible local model server.
8. FastAPI backend.
9. React or simple server-rendered dashboard.
10. Local file archive.
11. Optional Open WebUI for manual model interaction.

---

## 8. Architecture

### 8.1 High-Level Architecture

```text
                       ┌──────────────────────┐
                       │  Official Sources     │
                       │  Agendas / Notices    │
                       │  Staff Reports / PDFs │
                       └──────────┬───────────┘
                                  │
                                  ▼
                       ┌──────────────────────┐
                       │ n8n Scheduled Fetches │
                       │ Source Polling        │
                       └──────────┬───────────┘
                                  │
              ┌───────────────────┼───────────────────┐
              ▼                   ▼                   ▼
   ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
   │ Raw HTML Archive │  │ Raw PDF Archive  │  │ Metadata Records │
   └────────┬────────┘  └────────┬────────┘  └────────┬────────┘
            │                    │                    │
            └────────────┬───────┴────────────┬───────┘
                         ▼                    ▼
              ┌──────────────────┐  ┌──────────────────┐
              │ Document Parser   │  │ Dedup / Hashing   │
              └────────┬─────────┘  └────────┬─────────┘
                       │                     │
                       ▼                     ▼
              ┌─────────────────────────────────────┐
              │ PostgreSQL + pgvector                │
              │ documents, meetings, issues, events  │
              └──────────────────┬──────────────────┘
                                 │
                                 ▼
                   ┌────────────────────────┐
                   │ Local AI Workers        │
                   │ classify, summarize,    │
                   │ extract, cluster        │
                   └───────────┬────────────┘
                               │
                ┌──────────────┼──────────────┐
                ▼              ▼              ▼
       ┌─────────────┐ ┌─────────────┐ ┌─────────────┐
       │ Review Queue │ │ Alerts       │ │ Dashboard    │
       └─────────────┘ └─────────────┘ └─────────────┘
```

### 8.2 Deployment Model

All core services should run on `madhatter` under Docker Compose.

Suggested containers:

1. `postgres`
2. `n8n`
3. `civic-api`
4. `civic-worker`
5. `civic-dashboard`
6. `ollama`
7. `redis`
8. `minio` or local object-store equivalent, optional
9. `watchtower` or manual update process, optional
10. `prometheus` and `grafana`, optional for later phase

For Phase 1, local filesystem archive is acceptable. MinIO can be added later if object management becomes useful.

---

## 9. Functional Requirements

## 9.1 Source Registry

The system must maintain a registry of monitored sources.

Each source should include:

1. Source name.
2. Jurisdiction.
3. Agency.
4. Body or department.
5. Source type.
6. URL.
7. Fetch method.
8. Polling frequency.
9. Expected content type.
10. Parser type.
11. Reliability score.
12. Last successful fetch.
13. Last changed timestamp.
14. Known limitations.
15. Whether source is official, media, advocacy, or social.

Source types:

1. Agenda center.
2. Meeting body page.
3. Public notice page.
4. PDF directory.
5. HTML page.
6. RSS feed.
7. Campaign filing portal.
8. Election page.
9. News site.
10. Newsletter.
11. Manual upload.
12. Social post submission.

Source authority levels:

1. Official primary source.
2. Official secondary source.
3. Media source.
4. Advocacy source.
5. Community/social source.
6. Manual unverified source.

Acceptance criteria:

1. Operator can add, edit, disable, and annotate sources.
2. Each fetch is associated with a source record.
3. Source reliability and authority are visible in the dashboard.
4. Failed sources appear in a monitoring view.

---

## 9.2 Scheduled Ingestion

The system must fetch monitored sources on a schedule.

Default polling intervals:

1. High-priority agenda and notice sources: every 2–4 hours.
2. Public-notice pages: every 4 hours.
3. Campaign-finance portals: daily.
4. News and newsletters: daily or twice daily.
5. Slow-changing reference pages: weekly.
6. Manual social submissions: on demand.

The ingestion system must:

1. Fetch HTML pages.
2. Download linked PDFs and attachments.
3. Detect new or changed documents.
4. Compute SHA-256 hashes.
5. Preserve raw fetched data.
6. Store fetch status and error messages.
7. Avoid repeated duplicate downloads.
8. Respect rate limits.
9. Avoid aggressive scraping.
10. Log all changes.

Acceptance criteria:

1. New agenda documents are detected without manual intervention.
2. Changed documents produce new version records.
3. Duplicate documents are not reprocessed unnecessarily.
4. Fetch failures are visible.
5. Raw source material is recoverable from the archive.

---

## 9.3 Raw Archive

The system must store original source material.

Archive contents:

1. Raw HTML.
2. Downloaded PDFs.
3. Word documents, if encountered.
4. Images and screenshots.
5. CSV files.
6. Campaign-finance filings.
7. Extracted text.
8. Source metadata JSON.
9. Fetch logs.

Archive path example:

```text
/archive/
  city_of_ventura/
    planning_commission/
      2026/
        2026-06-24/
          agenda.html
          staff_report_PROJ-26-1129.pdf
          supplemental_packet_1.pdf
          metadata.json
```

Each archived item should include:

1. Original URL.
2. Fetch timestamp.
3. SHA-256 hash.
4. Source ID.
5. Content type.
6. File size.
7. HTTP status.
8. Document date if detected.
9. Meeting date if detected.
10. Parser version.

Acceptance criteria:

1. Any dashboard item links back to a local archived copy.
2. Original external URL is preserved.
3. Changed documents are versioned.
4. The archive survives database rebuilds.

---

## 9.4 Document Parsing

The system must parse documents into usable text and metadata.

Supported formats:

1. HTML.
2. PDF.
3. DOCX.
4. TXT.
5. CSV.
6. Images/screenshots, optional OCR.

PDF parsing strategy:

1. Attempt direct text extraction first.
2. Detect scanned/image-heavy PDFs.
3. Use OCR only when necessary.
4. Preserve page boundaries.
5. Extract tables where practical.
6. Keep document-to-page mapping.

Parser output should include:

1. Full text.
2. Page-level text.
3. Section headings.
4. Tables, if detected.
5. Document title.
6. Meeting date.
7. Agenda item number.
8. Staff report author, if detected.
9. Project number, if detected.
10. Applicant, if detected.
11. Address or parcel number, if detected.
12. Ordinance or resolution number, if detected.
13. Public hearing date, if detected.
14. Comment deadline, if detected.

Acceptance criteria:

1. Text is searchable.
2. Page references are preserved.
3. Staff reports and agenda packets can be summarized by section.
4. Parser failures are stored and visible.

---

## 9.5 Meetings and Agenda Items

The system must detect and structure public meetings.

Meeting record fields:

1. Agency.
2. Body.
3. Meeting date.
4. Meeting time.
5. Location.
6. Remote participation link, if available.
7. Agenda URL.
8. Packet URL.
9. Minutes URL.
10. Video URL, if available.
11. Meeting type.
12. Regular, special, emergency, workshop, hearing, etc.
13. Source ID.
14. Fetch timestamp.
15. Status: scheduled, completed, minutes posted, video posted.

Agenda item fields:

1. Meeting ID.
2. Item number.
3. Title.
4. Short description.
5. Staff recommendation.
6. Department.
7. Action type.
8. Hearing required flag.
9. Vote expected flag.
10. Consent calendar flag.
11. Public-comment flag.
12. Documents attached.
13. Related issue IDs.
14. AI relevance score.
15. Human-reviewed status.

Action types:

1. Receive and file.
2. Discussion.
3. Direction to staff.
4. First reading.
5. Second reading/adoption.
6. Ordinance amendment.
7. Resolution.
8. Public hearing.
9. Permit approval.
10. Appeal.
11. Contract approval.
12. Budget action.
13. Appointment.
14. Election/campaign action.

Acceptance criteria:

1. Agenda items can be browsed by meeting.
2. Agenda items can be searched across agencies.
3. The system detects new agenda items since the last fetch.
4. The system flags items likely to involve votes or hearings.

---

## 9.6 Issue Tracking

The issue is the central product object.

An issue represents a civic matter that may evolve over time.

Examples:

1. Public Notice Procedures Ordinance Amendments.
2. Ventura hillside development notice changes.
3. Coastal permit notice changes.
4. Downtown parking ordinance.
5. Water-rate increase.
6. Housing Element implementation.
7. Short-term rental regulation.
8. Campaign-finance spike in District 3.
9. School closure proposal.
10. Homeless-services contract.
11. Police budget increase.
12. CEQA challenge on a development project.

Issue fields:

1. Issue ID.
2. Title.
3. Slug.
4. Summary.
5. Jurisdiction.
6. Agencies involved.
7. Topic category.
8. Geography.
9. Districts affected.
10. Current status.
11. Importance score.
12. Urgency score.
13. Controversy score.
14. Transparency risk score.
15. Financial impact score.
16. Legal/procedural complexity score.
17. First detected date.
18. Last updated date.
19. Next deadline.
20. Next meeting.
21. Decision-makers.
22. Known supporters.
23. Known opponents.
24. Source confidence.
25. Human review status.
26. Publication status.

Issue statuses:

1. New.
2. Monitoring.
3. Hearing scheduled.
4. Vote scheduled.
5. Public comment open.
6. Continued.
7. Approved.
8. Rejected.
9. Appealed.
10. Litigated.
11. Dormant.
12. Closed.
13. Unknown.

Acceptance criteria:

1. Multiple agenda items and documents can attach to one issue.
2. Issue timeline is automatically updated when related source material appears.
3. Operator can manually merge or split issues.
4. Issue page shows current status, timeline, sources, and upcoming deadlines.

---

## 9.7 Issue Events

An issue event is any dated occurrence relevant to an issue.

Issue event types:

1. Application filed.
2. Courtesy notice issued.
3. Public notice posted.
4. Agenda posted.
5. Staff report posted.
6. Supplemental packet posted.
7. Public hearing scheduled.
8. Public comment deadline.
9. Meeting held.
10. Vote taken.
11. Continued to later date.
12. Appeal filed.
13. Ordinance introduced.
14. Ordinance adopted.
15. Lawsuit filed.
16. Campaign filing posted.
17. News article published.
18. Social claim detected.
19. Public comment submitted.
20. Staff revision posted.

Issue event fields:

1. Issue ID.
2. Event date.
3. Detected date.
4. Event type.
5. Title.
6. Description.
7. Source document.
8. Source authority.
9. Confidence.
10. Extracted by.
11. Reviewed by.
12. Public visibility.

Acceptance criteria:

1. Every issue has a chronological timeline.
2. Events preserve source links.
3. Social/community claims are visibly marked as unverified unless confirmed.
4. The system can show “what changed since yesterday.”

---

## 9.8 AI Classification

The AI system must classify incoming items.

Classification dimensions:

1. Jurisdiction.
2. Agency.
3. Topic category.
4. Civic importance.
5. Urgency.
6. Public participation opportunity.
7. Transparency risk.
8. Land-use relevance.
9. Campaign/election relevance.
10. Financial relevance.
11. Legal/procedural relevance.
12. Neighborhood impact.
13. Whether human review is required.

Initial topic taxonomy:

1. Land use.
2. Planning.
3. Zoning.
4. Coastal development.
5. Hillside development.
6. Housing.
7. CEQA/environment.
8. Public notice/transparency.
9. Elections.
10. Campaign finance.
11. Budget/tax/fees.
12. Water.
13. Transportation.
14. Police/public safety.
15. Homelessness.
16. Schools.
17. Parks/open space.
18. Cannabis.
19. Short-term rentals.
20. Public contracts.
21. Appointments/commissions.
22. Litigation.
23. Ethics/conflict of interest.
24. Infrastructure.
25. General governance.

Classification output should be stored as structured JSON.

Example output:

```json
{
  "topic_categories": ["public_notice", "planning", "coastal_development"],
  "jurisdiction": "City of Ventura",
  "agency": "Community Development Department",
  "importance_score": 8,
  "urgency_score": 7,
  "transparency_risk_score": 9,
  "public_participation_opportunity": true,
  "vote_expected": true,
  "hearing_expected": true,
  "human_review_required": true,
  "rationale": "Proposed ordinance changes would alter mailed and posted notice procedures for multiple entitlement types."
}
```

Acceptance criteria:

1. All new agenda items receive a topic classification.
2. High-risk classifications enter the review queue.
3. AI output is stored separately from source truth.
4. Operator can override classifications.

---

## 9.9 AI Summarization

The system must produce several summary types.

### 9.9.1 Document Summary

For each significant document:

1. Plain-English summary.
2. Key decision requested.
3. What changes from current policy.
4. Who is affected.
5. Dates and deadlines.
6. Staff recommendation.
7. Potential controversy.
8. Source confidence.
9. Key excerpts with page references, where possible.

### 9.9.2 Agenda Item Summary

For each agenda item:

1. What the item is.
2. Why it matters.
3. Whether action is expected.
4. Whether public comment is available.
5. Decision-makers.
6. Relevant documents.
7. Related issue.
8. Suggested watch level.

### 9.9.3 Issue Brief

For each tracked issue:

1. Current status.
2. Background.
3. Timeline.
4. What changed recently.
5. Next decision point.
6. Who decides.
7. Stakeholders.
8. Arguments for.
9. Arguments against.
10. Procedural concerns.
11. Open questions.
12. Source links.

### 9.9.4 Daily Digest Summary

Daily digest sections:

1. Top changes.
2. Upcoming hearings and votes.
3. New public notices.
4. New campaign/election items.
5. Items needing human review.
6. Items with approaching deadlines.
7. Low-confidence or unverified claims.

Acceptance criteria:

1. Summaries are source-linked.
2. AI summaries clearly distinguish facts from inference.
3. High-risk summaries require human review before public use.
4. System can regenerate summaries with a newer prompt/model.

---

## 9.10 Structured Extraction

The system must extract structured fields from documents and pages.

Entities to extract:

1. Person names.
2. Official titles.
3. Agencies.
4. Boards and commissions.
5. Applicants.
6. Property owners.
7. Developers.
8. Contractors.
9. Consultants.
10. Addresses.
11. APNs.
12. Districts.
13. Ordinance numbers.
14. Resolution numbers.
15. Project numbers.
16. Permit numbers.
17. Meeting dates.
18. Hearing dates.
19. Comment deadlines.
20. Vote results.
21. Dollar amounts.
22. Contract amounts.
23. Campaign contributions.
24. Filing dates.

Acceptance criteria:

1. Extracted entities are searchable.
2. Operator can correct extracted entities.
3. Corrections should improve future matching where practical.
4. Extracted deadlines can trigger alerts.

---

## 9.11 Issue Clustering

The system must detect when a new item belongs to an existing issue.

Clustering methods:

1. Keyword matching.
2. Exact project number matching.
3. Ordinance/resolution number matching.
4. Applicant/address/APN matching.
5. Embedding similarity.
6. AI semantic comparison.
7. Manual merge.

Similarity signals:

1. Same project number.
2. Same ordinance title.
3. Same address or APN.
4. Same applicant.
5. Same agency and topic.
6. Similar title.
7. Similar summary.
8. Repeated staff report language.
9. Same public hearing series.

Acceptance criteria:

1. System proposes likely issue matches.
2. Operator can accept, reject, or merge.
3. False positives are visible and correctable.
4. Issue pages update after accepted matches.

---

## 9.12 Alerts

The system must generate alerts when meaningful changes occur.

Alert channels:

1. Dashboard.
2. Email.
3. Optional Slack/Discord.
4. Optional SMS later.
5. Optional RSS feed.
6. Optional static web page.

Alert levels:

### Level 1 — Captured

A new item was found and archived.

Examples:

1. New agenda posted.
2. New staff report downloaded.
3. New public notice found.

### Level 2 — Relevant

Item is politically or civically relevant but not urgent.

Examples:

1. Routine planning update.
2. Low-impact commission appointment.
3. Informational report.

### Level 3 — Action Window

Item has a hearing, deadline, comment opportunity, or vote within seven days.

Examples:

1. Planning Commission hearing next week.
2. Public comment period closing soon.
3. Council vote scheduled.

### Level 4 — High Impact / Imminent

Item is both important and time-sensitive.

Examples:

1. Ordinance changing public notice rules.
2. Coastal/hillside development approval.
3. Major fee increase.
4. Campaign-finance anomaly.
5. Late supplemental packet on controversial matter.
6. Special meeting with 24-hour notice.

Alert fields:

1. Alert title.
2. Issue ID.
3. Alert level.
4. Trigger.
5. Summary.
6. Deadline.
7. Meeting date.
8. Source link.
9. Confidence.
10. Review status.

Acceptance criteria:

1. Alerts are generated automatically.
2. Operator can mute sources, topics, or issues.
3. Alerts are not sent repeatedly for the same unchanged item.
4. Level 4 alerts are visibly separated from routine updates.

---

## 9.13 Dashboard

The dashboard should be issue-centric.

### 9.13.1 Home Page

Home page sections:

1. What changed since last review.
2. High-impact alerts.
3. Upcoming votes and hearings.
4. Open public-comment windows.
5. New public notices.
6. New agenda items.
7. New campaign/election filings.
8. Items needing review.
9. Source failures.
10. Recently updated issues.

### 9.13.2 Issue Page

Issue page sections:

1. Title.
2. Status.
3. Summary.
4. Why it matters.
5. Timeline.
6. Next deadline.
7. Next meeting.
8. Agencies involved.
9. Decision-makers.
10. Source documents.
11. Extracted entities.
12. AI analysis.
13. Human notes.
14. Publication draft.
15. Related issues.

### 9.13.3 Meeting Page

Meeting page sections:

1. Agency/body.
2. Date/time.
3. Location.
4. Agenda link.
5. Packet link.
6. Agenda items.
7. Flagged items.
8. AI meeting summary.
9. Related issues.
10. Post-meeting vote/minutes status.

### 9.13.4 Source Page

Source page sections:

1. Source name.
2. URL.
3. Last fetched.
4. Last changed.
5. Fetch history.
6. Failure count.
7. Documents found.
8. Parser status.
9. Notes.

### 9.13.5 Review Queue

Review queue filters:

1. High-impact.
2. Urgent.
3. Low-confidence.
4. Social/unverified.
5. Publication candidate.
6. Extraction errors.
7. Possible duplicate issue.
8. Source failure.

Acceptance criteria:

1. Operator can move from alert to source document in one click.
2. Operator can approve, edit, or reject AI summaries.
3. Operator can assign items to issues.
4. Dashboard is usable locally without cloud dependencies.

---

## 9.14 Search

The system must provide full-text and semantic search.

Search targets:

1. Documents.
2. Agenda items.
3. Issues.
4. Public notices.
5. Extracted entities.
6. Meeting records.
7. Campaign filings.
8. Human notes.
9. AI summaries.

Search modes:

1. Keyword search.
2. Exact phrase search.
3. Entity search.
4. Date-filtered search.
5. Agency-filtered search.
6. Semantic search.
7. Similar document search.

Acceptance criteria:

1. User can search “public notice ordinance” and find relevant agenda items and documents.
2. User can search by project number.
3. User can search by address or APN.
4. User can find documents by agency, date, and topic.
5. Semantic search returns related issues even when wording differs.

---

## 9.15 Publishing and Exports

The system should support human-approved output.

Output types:

1. Daily internal digest.
2. Weekly civic radar brief.
3. Urgent alert.
4. Issue brief.
5. Markdown export.
6. HTML export.
7. Email draft.
8. CSV export.
9. JSON API.
10. Static archive page, optional.

Each published item should include:

1. Title.
2. Date.
3. Summary.
4. Why it matters.
5. What changed.
6. Next action/deadline.
7. Source links.
8. Confidence note.
9. Human review status.

Acceptance criteria:

1. No public-facing item is published without review.
2. Markdown export is clean and editable.
3. Source links are preserved.
4. Unverified social claims are labeled.

---

## 10. AI Architecture

## 10.1 Local Model Usage

The local AI system on `madhatter` should be used for:

1. Triage.
2. Classification.
3. Structured extraction.
4. Summarization.
5. Issue matching.
6. Draft alerts.
7. Draft briefs.
8. Semantic search.
9. Claim verification assistance.

Recommended model tiers:

### Fast Triage Model

Purpose:

1. Classify short items.
2. Extract obvious metadata.
3. Decide whether to escalate.

Typical size:

1. 7B–8B.

### Strong Local Analysis Model

Purpose:

1. Summarize staff reports.
2. Compare ordinance versions.
3. Generate issue briefs.
4. Extract nuanced implications.

Typical size:

1. 14B or quantized larger model if performance permits.

### Embedding Model

Purpose:

1. Semantic search.
2. Issue clustering.
3. Similarity detection.

Requirements:

1. Local embedding server.
2. Store vectors in pgvector.
3. Chunk documents by page/section.

---

## 10.2 AI Pipeline

For each new document:

1. Parse document.
2. Chunk by section/page.
3. Generate embeddings.
4. Extract metadata.
5. Classify relevance.
6. Match to existing issue.
7. Summarize chunk-level content.
8. Produce document-level summary.
9. Detect dates/deadlines.
10. Create or update issue events.
11. Create alert if thresholds are met.
12. Send high-risk items to review queue.

Example pipeline:

```text
New PDF
  → hash check
  → archive
  → text extraction
  → page/section chunking
  → embeddings
  → metadata extraction
  → agenda/project/entity extraction
  → classification
  → issue matching
  → summary generation
  → alert scoring
  → review queue
```

---

## 10.3 Prompt Management

Prompts should be versioned.

Prompt records should include:

1. Prompt ID.
2. Task type.
3. Prompt text.
4. Model name.
5. Model parameters.
6. JSON schema expected.
7. Date created.
8. Active/inactive.
9. Notes.

Prompt task types:

1. Agenda item classification.
2. Public notice extraction.
3. Staff report summary.
4. Ordinance comparison.
5. Campaign filing extraction.
6. Social claim triage.
7. Issue brief generation.
8. Alert generation.
9. Deadline extraction.
10. Entity extraction.

Acceptance criteria:

1. AI outputs are traceable to prompt version and model.
2. Prompts can be updated without losing old outputs.
3. Failed JSON responses are retried or sent to review.

---

## 10.4 AI Guardrails

The AI must:

1. Distinguish source facts from inference.
2. Avoid defamatory conclusions.
3. Treat social claims as unverified.
4. Avoid asserting corruption, illegality, or bad faith unless source-supported.
5. Flag legal complexity.
6. Flag low confidence.
7. Never overwrite raw source records.
8. Provide document/page references where possible.
9. Avoid fabricating missing source links.
10. Preserve uncertainty.

High-risk content requiring human review:

1. Allegations of corruption.
2. Conflict-of-interest claims.
3. Campaign-finance anomalies.
4. Accusations against named individuals.
5. Legal interpretations.
6. CEQA/legal challenge analysis.
7. Health/safety claims.
8. Claims from social media.
9. Any item marked Level 4.
10. Any item with low confidence but high importance.

---

## 11. Data Model

## 11.1 Core Tables

### `sources`

```sql
CREATE TABLE sources (
  id UUID PRIMARY KEY,
  name TEXT NOT NULL,
  jurisdiction TEXT,
  agency TEXT,
  body TEXT,
  source_type TEXT NOT NULL,
  authority_level TEXT NOT NULL,
  url TEXT NOT NULL,
  fetch_method TEXT NOT NULL,
  polling_interval_minutes INTEGER,
  parser_type TEXT,
  enabled BOOLEAN DEFAULT TRUE,
  reliability_score INTEGER DEFAULT 5,
  notes TEXT,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);
```

### `fetches`

```sql
CREATE TABLE fetches (
  id UUID PRIMARY KEY,
  source_id UUID REFERENCES sources(id),
  fetched_at TIMESTAMPTZ DEFAULT now(),
  status TEXT NOT NULL,
  http_status INTEGER,
  content_hash TEXT,
  archive_path TEXT,
  error_message TEXT,
  duration_ms INTEGER,
  changed BOOLEAN DEFAULT FALSE
);
```

### `documents`

```sql
CREATE TABLE documents (
  id UUID PRIMARY KEY,
  source_id UUID REFERENCES sources(id),
  fetch_id UUID REFERENCES fetches(id),
  title TEXT,
  document_type TEXT,
  original_url TEXT,
  archive_path TEXT,
  content_hash TEXT NOT NULL,
  mime_type TEXT,
  file_size_bytes BIGINT,
  document_date DATE,
  meeting_date DATE,
  jurisdiction TEXT,
  agency TEXT,
  body TEXT,
  project_number TEXT,
  ordinance_number TEXT,
  resolution_number TEXT,
  parser_status TEXT DEFAULT 'pending',
  extracted_text_path TEXT,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);
```

### `document_chunks`

```sql
CREATE TABLE document_chunks (
  id UUID PRIMARY KEY,
  document_id UUID REFERENCES documents(id),
  chunk_index INTEGER NOT NULL,
  page_start INTEGER,
  page_end INTEGER,
  section_title TEXT,
  text TEXT NOT NULL,
  token_count INTEGER,
  embedding vector,
  created_at TIMESTAMPTZ DEFAULT now()
);
```

### `meetings`

```sql
CREATE TABLE meetings (
  id UUID PRIMARY KEY,
  jurisdiction TEXT NOT NULL,
  agency TEXT NOT NULL,
  body TEXT NOT NULL,
  meeting_type TEXT,
  start_time TIMESTAMPTZ,
  end_time TIMESTAMPTZ,
  location TEXT,
  remote_url TEXT,
  agenda_document_id UUID REFERENCES documents(id),
  packet_document_id UUID REFERENCES documents(id),
  minutes_document_id UUID REFERENCES documents(id),
  video_url TEXT,
  status TEXT DEFAULT 'scheduled',
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);
```

### `agenda_items`

```sql
CREATE TABLE agenda_items (
  id UUID PRIMARY KEY,
  meeting_id UUID REFERENCES meetings(id),
  item_number TEXT,
  title TEXT NOT NULL,
  description TEXT,
  department TEXT,
  staff_recommendation TEXT,
  action_type TEXT,
  consent_calendar BOOLEAN DEFAULT FALSE,
  public_hearing BOOLEAN DEFAULT FALSE,
  vote_expected BOOLEAN DEFAULT FALSE,
  relevance_score INTEGER,
  urgency_score INTEGER,
  transparency_risk_score INTEGER,
  ai_summary TEXT,
  human_summary TEXT,
  review_status TEXT DEFAULT 'unreviewed',
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);
```

### `issues`

```sql
CREATE TABLE issues (
  id UUID PRIMARY KEY,
  title TEXT NOT NULL,
  slug TEXT UNIQUE,
  summary TEXT,
  jurisdiction TEXT,
  status TEXT DEFAULT 'new',
  importance_score INTEGER DEFAULT 0,
  urgency_score INTEGER DEFAULT 0,
  controversy_score INTEGER DEFAULT 0,
  transparency_risk_score INTEGER DEFAULT 0,
  financial_impact_score INTEGER DEFAULT 0,
  legal_complexity_score INTEGER DEFAULT 0,
  first_detected_at TIMESTAMPTZ,
  last_updated_at TIMESTAMPTZ,
  next_deadline TIMESTAMPTZ,
  next_meeting_id UUID REFERENCES meetings(id),
  source_confidence TEXT,
  review_status TEXT DEFAULT 'unreviewed',
  publication_status TEXT DEFAULT 'internal',
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);
```

### `issue_events`

```sql
CREATE TABLE issue_events (
  id UUID PRIMARY KEY,
  issue_id UUID REFERENCES issues(id),
  event_type TEXT NOT NULL,
  event_date TIMESTAMPTZ,
  detected_at TIMESTAMPTZ DEFAULT now(),
  title TEXT NOT NULL,
  description TEXT,
  document_id UUID REFERENCES documents(id),
  agenda_item_id UUID REFERENCES agenda_items(id),
  source_authority TEXT,
  confidence TEXT,
  reviewed BOOLEAN DEFAULT FALSE,
  created_at TIMESTAMPTZ DEFAULT now()
);
```

### `issue_links`

```sql
CREATE TABLE issue_links (
  id UUID PRIMARY KEY,
  issue_id UUID REFERENCES issues(id),
  document_id UUID REFERENCES documents(id),
  agenda_item_id UUID REFERENCES agenda_items(id),
  relationship_type TEXT,
  confidence TEXT,
  created_by TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);
```

### `entities`

```sql
CREATE TABLE entities (
  id UUID PRIMARY KEY,
  entity_type TEXT NOT NULL,
  canonical_name TEXT NOT NULL,
  aliases TEXT[],
  notes TEXT,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);
```

### `entity_mentions`

```sql
CREATE TABLE entity_mentions (
  id UUID PRIMARY KEY,
  entity_id UUID REFERENCES entities(id),
  document_id UUID REFERENCES documents(id),
  agenda_item_id UUID REFERENCES agenda_items(id),
  issue_id UUID REFERENCES issues(id),
  mention_text TEXT,
  page_number INTEGER,
  confidence TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);
```

### `alerts`

```sql
CREATE TABLE alerts (
  id UUID PRIMARY KEY,
  issue_id UUID REFERENCES issues(id),
  agenda_item_id UUID REFERENCES agenda_items(id),
  document_id UUID REFERENCES documents(id),
  alert_level INTEGER NOT NULL,
  title TEXT NOT NULL,
  summary TEXT,
  trigger_reason TEXT,
  deadline TIMESTAMPTZ,
  status TEXT DEFAULT 'new',
  sent_at TIMESTAMPTZ,
  reviewed BOOLEAN DEFAULT FALSE,
  created_at TIMESTAMPTZ DEFAULT now()
);
```

### `ai_outputs`

```sql
CREATE TABLE ai_outputs (
  id UUID PRIMARY KEY,
  task_type TEXT NOT NULL,
  model_name TEXT NOT NULL,
  prompt_version TEXT NOT NULL,
  input_ref_type TEXT NOT NULL,
  input_ref_id UUID NOT NULL,
  output_json JSONB,
  output_text TEXT,
  confidence TEXT,
  error_message TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);
```

---

## 12. Topic Scoring

The system should score importance, urgency, and risk.

### 12.1 Importance Score

Factors:

1. Number of residents affected.
2. Policy scope.
3. Financial impact.
4. Land-use impact.
5. Environmental impact.
6. Election impact.
7. Governance impact.
8. Legal significance.
9. Reversibility.
10. Public controversy.

Scale:

1. 0–2: routine.
2. 3–5: moderate.
3. 6–8: significant.
4. 9–10: major.

### 12.2 Urgency Score

Factors:

1. Days until hearing.
2. Days until vote.
3. Days until comment deadline.
4. Whether agenda was recently posted.
5. Whether supplemental packet was added late.
6. Whether special meeting.
7. Whether item is on consent calendar.
8. Whether public participation window is short.

Scale:

1. 0–2: no near-term action.
2. 3–5: action in 2–4 weeks.
3. 6–8: action within 7 days.
4. 9–10: action within 48 hours or already underway.

### 12.3 Transparency Risk Score

Factors:

1. Reduced notice radius.
2. Reduced sign size.
3. Eliminated early notice.
4. Complex agenda wording.
5. Late supplemental packet.
6. Consent calendar placement.
7. Unclear public-comment instructions.
8. Weak source discoverability.
9. Special meeting timing.
10. Major procedural change.

Scale:

1. 0–2: routine transparency.
2. 3–5: modest concern.
3. 6–8: significant transparency concern.
4. 9–10: severe transparency concern.

---

## 13. Source Strategy

## 13.1 Initial Official Sources

The initial source registry should include:

1. City of Ventura Agenda Center.
2. City of Ventura City Council meetings.
3. City of Ventura Planning Commission meetings.
4. City of Ventura public notices.
5. City of Ventura Community Development pages.
6. Ventura County Board of Supervisors agendas.
7. Ventura County Planning Commission agendas.
8. Ventura County RMA Planning pages.
9. Ventura County Elections pages.
10. Ventura County NetFile campaign filing portal.

## 13.2 Secondary Sources

Secondary sources may include:

1. Local newspapers.
2. Local newsletters.
3. Local advocacy organizations.
4. Candidate websites.
5. Campaign committee websites.
6. Neighborhood association pages.
7. Social media screenshots submitted manually.

## 13.3 Manual Submission Channel

The system should support manually submitted items.

Manual submission types:

1. Pasted text.
2. Screenshot.
3. PDF upload.
4. URL.
5. Email forward.
6. Note.

Manual submission fields:

1. Source description.
2. Claimed source.
3. Submission date.
4. Whether verified.
5. Related issue, if known.
6. Operator note.

Acceptance criteria:

1. A Nextdoor post can be saved as an unverified signal.
2. Operator can attach official sources later.
3. The dashboard distinguishes social claim from verified source material.

---

## 14. Review Workflow

The system should use a human-in-the-loop workflow.

Review states:

1. Unreviewed.
2. Needs source check.
3. Needs legal/policy review.
4. Needs rewrite.
5. Approved internal.
6. Approved for publication.
7. Rejected.
8. Archived only.

Review actions:

1. Approve AI classification.
2. Edit summary.
3. Assign to issue.
4. Merge issue.
5. Split issue.
6. Escalate to high priority.
7. Mark as false alarm.
8. Add human note.
9. Create alert.
10. Draft publication item.

Acceptance criteria:

1. High-impact items cannot be marked publication-ready without review.
2. Review history is stored.
3. Operator edits do not erase AI output.
4. Rejected items remain searchable.

---

## 15. User Workflows

## 15.1 Daily Review Workflow

1. Open dashboard.
2. Review “What changed since yesterday.”
3. Inspect Level 3 and Level 4 alerts.
4. Check upcoming hearings and deadlines.
5. Review AI summaries for top items.
6. Approve or correct issue assignments.
7. Draft daily internal digest.
8. Mark reviewed.

## 15.2 New Agenda Workflow

1. System detects new agenda.
2. Downloads agenda and packet.
3. Extracts agenda items.
4. Classifies items.
5. Matches items to issues.
6. Flags significant items.
7. Creates alerts for hearings/votes/deadlines.
8. Adds items to dashboard review queue.

## 15.3 Public Notice Workflow

1. System detects new public notice.
2. Extracts project title, address, hearing body, date, applicant, project number.
3. Geocodes address, if practical.
4. Matches to existing issue or creates new candidate issue.
5. Determines deadline and action window.
6. Alerts if affected category is high priority.

## 15.4 Social Claim Verification Workflow

1. User submits social post.
2. System stores it as unverified.
3. AI extracts claims.
4. System searches official sources for confirmation.
5. Claims are marked confirmed, contradicted, unresolved, or unverifiable.
6. Related issue is updated.
7. Publication requires human review.

## 15.5 Issue Brief Workflow

1. Operator opens issue.
2. Reviews timeline and sources.
3. Generates issue brief draft.
4. Edits summary and analysis.
5. Adds human judgment.
6. Exports Markdown.
7. Optionally sends as email/newsletter.

---

## 16. UI Requirements

## 16.1 Dashboard UX Principles

The UI should be fast, dense, and source-oriented.

Avoid:

1. Decorative analytics.
2. Overly broad newsfeed layout.
3. Hidden source links.
4. AI-generated summaries without source access.
5. Requiring many clicks to see deadlines.

Prefer:

1. Tables with sortable urgency.
2. Timeline views.
3. Clear source badges.
4. Review states.
5. One-click source document access.
6. “What changed” summaries.
7. Issue-first navigation.

## 16.2 Key Screens

### Screen: Home

Must show:

1. High-priority alerts.
2. New items since last visit.
3. Upcoming hearings.
4. Comment deadlines.
5. Review queue.
6. Source failures.

### Screen: Issue Detail

Must show:

1. Title.
2. Status.
3. Latest summary.
4. Timeline.
5. Documents.
6. Decision-makers.
7. Deadlines.
8. Related agenda items.
9. AI outputs.
10. Human notes.

### Screen: Meeting Detail

Must show:

1. Body.
2. Date/time.
3. Agenda items.
4. Flagged items.
5. Documents.
6. Related issues.
7. Meeting status.

### Screen: Document Detail

Must show:

1. Title.
2. Source.
3. Original URL.
4. Local archive path.
5. Extracted text.
6. AI summary.
7. Entities.
8. Related issues.
9. Parser status.

### Screen: Review Queue

Must show:

1. Item.
2. Alert level.
3. Reason flagged.
4. AI summary.
5. Source.
6. Review controls.

---

## 17. API Requirements

The backend should expose internal APIs.

Example endpoints:

```text
GET /api/issues
GET /api/issues/{id}
POST /api/issues
PATCH /api/issues/{id}

GET /api/meetings
GET /api/meetings/{id}

GET /api/agenda-items
GET /api/agenda-items/{id}

GET /api/documents
GET /api/documents/{id}

GET /api/alerts
PATCH /api/alerts/{id}

GET /api/review-queue
POST /api/review/{item_id}/approve
POST /api/review/{item_id}/reject

GET /api/search?q=
POST /api/manual-submissions

POST /api/ai/classify/{document_id}
POST /api/ai/summarize/{document_id}
POST /api/ai/match-issue/{document_id}
```

Authentication can be simple for Phase 1 if the dashboard is LAN-only. If public exposure is added, authentication must be upgraded.

---

## 18. Security and Privacy

## 18.1 Local-First Security

The system should assume:

1. Some source material is public.
2. Human notes may be private.
3. Draft political analysis may be sensitive.
4. Social submissions may contain personally identifiable information.
5. Publication mistakes may create reputational risk.

Requirements:

1. Dashboard should not be publicly exposed in Phase 1.
2. Use local network access or VPN only.
3. Store secrets outside code.
4. Use read-only source fetch credentials if any are needed.
5. Back up database and archive.
6. Log user actions.
7. Avoid sending sensitive drafts to cloud AI by default.
8. Mark private notes separately from publishable material.

## 18.2 Content Risk Controls

The system must flag:

1. Named-person allegations.
2. Corruption claims.
3. Conflict-of-interest claims.
4. Criminal allegations.
5. Legal conclusions.
6. Unverified social claims.
7. Claims sourced only to anonymous posts.

Publication should require human approval for these categories.

---

## 19. Observability

The system should expose operational health.

Metrics:

1. Sources fetched.
2. Fetch failures.
3. Documents downloaded.
4. Documents parsed.
5. Parser failures.
6. AI jobs queued.
7. AI jobs failed.
8. Alerts generated.
9. Review queue length.
10. Source freshness.
11. Disk usage.
12. Database size.
13. Model latency.
14. Worker memory use.

Dashboard health indicators:

1. All sources healthy.
2. Some sources stale.
3. Parser backlog.
4. AI backlog.
5. Archive disk pressure.
6. Failed jobs needing attention.

Acceptance criteria:

1. Operator can see if the system is silently failing.
2. Failed fetches do not disappear.
3. AI failures are retriable.
4. Disk usage is visible.

---

## 20. Hardware and Performance Requirements

## 20.1 Target Machine

Primary deployment: `madhatter`.

Assumed capabilities:

1. Debian host.
2. Docker.
3. NVIDIA GPU available to containers.
4. Approximately 16 GB GPU VRAM.
5. Approximately 32 GB system RAM.
6. Local storage sufficient for archived PDFs and extracted text.

## 20.2 Performance Expectations

Phase 1 target:

1. Handle 50–100 monitored sources.
2. Process 100–500 documents per week.
3. Support one primary dashboard user.
4. Summarize ordinary staff reports within minutes.
5. Maintain searchable archive.
6. Avoid running multiple large models simultaneously.

## 20.3 Resource Constraints

Risks:

1. RAM pressure from existing containers.
2. Long PDFs exceeding model context.
3. OCR workloads consuming CPU/RAM.
4. GPU contention.
5. Disk growth from archived packets.

Mitigations:

1. Use job queues.
2. Limit concurrent AI jobs.
3. Chunk documents.
4. Store raw archive efficiently.
5. Add container memory limits.
6. Avoid OCR unless required.
7. Use smaller models for triage.
8. Schedule heavy jobs during quiet hours.

---

## 21. Reliability Requirements

The system should be resilient to:

1. Source page changes.
2. PDF link changes.
3. Temporary network failures.
4. Duplicate documents.
5. Malformed PDFs.
6. AI JSON failures.
7. Model server downtime.
8. Database restarts.
9. Partial ingestion failures.

Requirements:

1. Jobs should be idempotent.
2. Fetches should be retryable.
3. Document hashes should prevent duplicate processing.
4. AI jobs should be retryable.
5. Parser failures should not block unrelated documents.
6. Source-specific parser errors should be visible.
7. Backups should be routine.

---

## 22. Backup and Retention

Retention policy:

1. Raw official documents: retain indefinitely.
2. Raw HTML snapshots: retain indefinitely or compress after 12 months.
3. AI outputs: retain with prompt/model metadata.
4. Logs: retain detailed logs for 30–90 days, summarized logs longer.
5. Manual submissions: retain unless removed by operator.
6. Database backups: daily local backup, weekly off-machine backup.

Backup targets:

1. Local backup directory.
2. NAS if available.
3. External drive or remote encrypted backup.

Acceptance criteria:

1. Database can be restored.
2. Archive can be restored.
3. Restore process is documented.
4. Backups are monitored.

---

## 23. Implementation Plan

## 23.1 Phase 0 — Prototype

Objective: Prove ingestion, parsing, classification, and issue tracking on a small source set.

Scope:

1. PostgreSQL schema.
2. Source registry.
3. n8n fetch for City of Ventura agenda center.
4. PDF download and archive.
5. Basic text extraction.
6. Local AI classification.
7. Simple dashboard or admin table.
8. Manual issue creation.
9. Markdown issue brief export.

Exit criteria:

1. System detects a new agenda item.
2. System archives source document.
3. System extracts text.
4. System classifies relevance.
5. System attaches item to an issue.
6. System creates a basic alert.

## 23.2 Phase 1 — Internal Production

Objective: Make system useful for daily monitoring.

Scope:

1. City of Ventura and selected county sources.
2. Full issue model.
3. Review queue.
4. Alert levels.
5. Daily digest.
6. Search.
7. Basic source health.
8. Manual social submission.
9. Human-approved Markdown export.

Exit criteria:

1. Daily dashboard reliably answers “what changed.”
2. High-impact items are flagged.
3. Source failures are visible.
4. AI summaries are useful but reviewable.
5. Raw archive is reliable.

## 23.3 Phase 2 — Expanded Coverage

Objective: Add more agencies and richer political tracking.

Scope:

1. Additional cities.
2. School boards.
3. Water districts.
4. LAFCo.
5. Campaign-finance extraction.
6. Candidate tracking.
7. Geocoded project locations.
8. Improved entity resolution.
9. Better public-facing exports.

Exit criteria:

1. Multiple jurisdictions tracked.
2. Campaign filings summarized.
3. District/geography filtering works.
4. Issue pages support public-ready briefs.

## 23.4 Phase 3 — Publication Product

Objective: Publish resident-facing civic intelligence.

Scope:

1. Public website or newsletter workflow.
2. Subscription alerts.
3. User topic preferences.
4. Public archive pages.
5. Interactive issue maps.
6. Public comment deadline calendar.
7. More robust authentication.
8. Editorial workflow.

Exit criteria:

1. Public content can be produced safely.
2. Human review is enforced.
3. Residents can subscribe by issue/topic/geography.
4. Source-backed issue briefs are publishable.

---

## 24. Acceptance Criteria by Capability

### Ingestion

1. New agenda pages are detected.
2. New PDFs are downloaded.
3. Changed documents are versioned.
4. Source failures are visible.

### Parsing

1. PDFs produce searchable text.
2. Page boundaries are preserved.
3. Parser errors are logged.

### AI

1. Agenda items are classified.
2. Documents are summarized.
3. Deadlines are extracted.
4. Issue matches are proposed.
5. High-risk outputs require review.

### Issues

1. Operator can create, merge, split, and close issues.
2. Issue timeline updates automatically.
3. Issue page links to source documents.

### Alerts

1. Urgent items are flagged.
2. Duplicate alerts are suppressed.
3. Alerts include source links and deadlines.

### Dashboard

1. Home page shows changed items.
2. Review queue is actionable.
3. Search works across documents and issues.

### Publishing

1. Markdown export works.
2. Public-facing output requires review.
3. Unverified claims are labeled.

---

## 25. Open Questions

1. Should Phase 1 include only City of Ventura, or City of Ventura plus County Board and County Planning?
2. Should the first dashboard be a quick internal admin UI or a polished reader-facing interface?
3. Should campaign-finance tracking be included in Phase 1 or Phase 2?
4. Should the system geocode project addresses in Phase 1?
5. Should meeting video/transcripts be deferred until after the document pipeline is stable?
6. Should daily digest be emailed or just shown in dashboard?
7. Should social submissions be manual-only at first?
8. Should cloud AI be completely disabled by default or available as a manual escalation?
9. What is the preferred publication format: internal memo, newsletter, blog, or alert feed?
10. How much historical backfill is needed before going live?

---

## 26. Key Risks

### 26.1 Source Fragility

Local government websites often have inconsistent URLs, agenda systems, document naming, and supplemental packets.

Mitigation:

1. Store raw snapshots.
2. Build source-specific parsers.
3. Monitor failures.
4. Keep manual upload path.

### 26.2 AI Overstatement

AI may infer motives, legal consequences, or political implications too strongly.

Mitigation:

1. Require human review.
2. Store source facts separately.
3. Use cautious templates.
4. Flag legal/reputational risk.

### 26.3 Long Document Complexity

Staff reports and agenda packets may exceed local model context.

Mitigation:

1. Chunk documents.
2. Summarize by section.
3. Extract structured metadata before summarization.
4. Use final synthesis from intermediate summaries.

### 26.4 Operator Overload

Too many alerts can make the system noisy.

Mitigation:

1. Alert levels.
2. Topic filters.
3. Review queue prioritization.
4. Muting and watchlists.

### 26.5 Hardware Contention

`madhatter` may run other services, causing RAM and GPU contention.

Mitigation:

1. Queue AI jobs.
2. Limit concurrency.
3. Use smaller models for triage.
4. Monitor resource usage.
5. Schedule heavy processing.

---

## 27. Recommended MVP Build

The minimum useful build should include:

1. PostgreSQL with core schema.
2. Local archive directory.
3. n8n scheduled fetches.
4. City of Ventura agenda ingestion.
5. City of Ventura Planning Commission ingestion.
6. PDF text extraction.
7. Local AI classification.
8. Local AI document summary.
9. Manual issue creation.
10. Issue timeline.
11. Alert scoring.
12. Review queue.
13. Markdown issue brief export.

MVP success condition:

The system should be able to ingest a Planning Commission agenda item like a public-notice ordinance amendment, archive the staff report, identify the item as high-transparency-risk, summarize the actual proposed changes, attach it to a tracked issue, identify the next meeting/deadline, and produce a reviewable Markdown brief.

---

## 28. Example Issue Brief Output

```markdown
# Public Notice Procedures Ordinance Amendments

Status: Hearing scheduled  
Jurisdiction: City of Ventura  
Agencies: Planning Commission, City Council, Community Development Department  
Importance: High  
Urgency: High  
Transparency Risk: High  

## What Happened

The City of Ventura placed a proposed public-notice ordinance amendment on the Planning Commission agenda. The proposal would modify how public notices are mailed, posted, and structured for multiple planning and entitlement actions.

## Why It Matters

The proposal may reduce early awareness of certain projects by eliminating some courtesy notices and standardizing notice distances. It may also reduce physical sign visibility by replacing larger posted signs with smaller signs.

## What Changed Recently

A staff report and draft ordinance were posted for Planning Commission review. Supplemental materials were later added.

## Next Decision Point

Planning Commission hearing scheduled for [date/time]. City Council consideration may follow if the Planning Commission recommends approval.

## Key Documents

- Planning Commission agenda
- Staff report
- Draft ordinance
- Supplemental packet

## Open Questions

1. Which notice categories are reduced from more than 300 feet to 300 feet?
2. Which notices are eliminated entirely?
3. Does the proposal affect coastal-zone notice requirements?
4. What public-facing alternative notice system, if any, replaces larger signs or early courtesy notices?

## Assessment

This is a procedural governance issue with high transparency implications. The substance is not a direct land-use approval, but it may affect residents’ ability to learn about and respond to future land-use approvals.
```

---

## 29. Naming

Working product names:

1. Ventura Civic Radar.
2. Ventura Issue Radar.
3. CivicWatch Ventura.
4. Ventura Public Notice Monitor.
5. County Civic Radar.
6. LocalGov Radar.
7. Civic Signal Ventura.

Recommended internal name: Ventura Civic Radar.

---

## 30. Final Recommendation

Build Ventura Civic Radar as a local-first, source-archiving, issue-centric intelligence system.

Do not begin with a public website. Begin with reliable ingestion, archiving, classification, issue timelines, and reviewable alerts. The product’s value will come from early detection, accurate source preservation, and clear issue tracking. Public-facing output should come only after the internal system reliably distinguishes official facts, AI inference, and unverified community claims.

The first successful version should be able to answer, every morning:

1. What changed?
2. What matters?
3. What deadline is approaching?
4. What documents prove it?
5. What needs human review?

