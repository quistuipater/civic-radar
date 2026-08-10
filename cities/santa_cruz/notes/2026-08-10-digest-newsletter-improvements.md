# Santa Cruz Digest Newsletter Improvements

Date: 2026-08-10

## Context

A newsletter-style summary was requested for "the last week of intelligence from Santa Cruz Civic Radar," but the available endpoint at `/api/digest/daily.md` produced a daily digest covering only the last 24 hours.

The generated digest was useful as a current civic brief, but it exposed several product gaps that should be addressed before treating the output as a weekly newsletter source.

## Observed issues

1. The digest title and endpoint are explicitly daily, but a user may reasonably ask for a weekly rollup and expect the system to aggregate seven days of intelligence.
2. The current daily digest can be adapted into newsletter prose, but it does not provide enough temporal context to distinguish a one-day quiet period from a genuinely quiet week.
3. NetFile RSS source snapshots appeared repeatedly in the "New Campaign/Election Items" section, creating duplicate entries that are source captures rather than distinct civic intelligence items.
4. Filing-level items and feed-level snapshots are mixed together, which makes the campaign/election section noisy.
5. Low-confidence items are correctly flagged, but the digest does not explain what specific human review question needs to be resolved.
6. The digest is internally useful, but it needs an additional editorial/newsletter layer before public use.

## Recommended changes

### Add a weekly digest endpoint

Add an endpoint such as:

```text
GET /api/digest/weekly.md
```

The endpoint should default to the last seven calendar days and should also support explicit date parameters:

```text
GET /api/digest/weekly.md?start=2026-08-03&end=2026-08-10
```

The weekly digest should not simply concatenate seven daily digests. It should aggregate, rank, deduplicate, and summarize issue movement over the full period.

### Add newsletter-ready output

Add a second output mode or endpoint for publication drafting:

```text
GET /api/digest/newsletter.md?days=7
```

This should produce prose suitable for human review, with sections such as:

- Lead item
- What moved this week
- Hearings and votes ahead
- Campaign and disclosure watch
- Planning and land-use watch
- Items needing human review
- System notes

The output should remain clearly marked as an internal draft unless a human explicitly approves it.

### Deduplicate campaign/election source snapshots

NetFile RSS snapshots should be deduplicated before appearing in digest output. The digest should favor distinct filings over repeated feed captures.

Possible rules:

- Collapse repeated snapshots by `source_id`, `original_url`, and date.
- Show the source feed once under a "Sources updated" or "Feeds checked" section if needed.
- Promote individual filings to the main campaign/election section.
- Suppress unchanged feed snapshots from newsletter output.

### Separate feed captures from civic items

The digest should distinguish:

- Source snapshots
- Actual filings
- Agenda items
- Public notices
- Meeting actions
- AI-generated issue updates

A source snapshot is evidence that the system checked or archived a feed. It is not, by itself, necessarily a civic intelligence item.

### Improve human-review prompts

For low-confidence or unreviewed items, the digest should include a specific review reason, for example:

- Confirm whether this filing is materially relevant.
- Confirm whether this item belongs to an existing issue.
- Verify the extracted date range.
- Check whether this is a duplicate feed snapshot.

### Add weekly issue movement logic

A weekly digest should prioritize issues that changed during the period, not just documents captured during the period.

Useful issue-movement signals:

- New issue created
- Existing issue received a new hearing date
- Vote or action occurred
- Staff report posted
- Supplemental packet added
- Public comment window opened or closed
- Campaign filing attached to an existing issue or person
- Human review changed issue status

## Acceptance criteria

- A user asking for "last week" receives a true seven-day rollup, not a 24-hour digest rewritten as if weekly.
- Repeated NetFile RSS snapshots no longer dominate the campaign/election section.
- Distinct filings remain visible.
- Weekly output includes issue movement, upcoming deadlines, hearings and votes.
- Newsletter output is readable as prose but remains marked as a draft until reviewed.
- Low-confidence items explain what needs to be checked.

## Example desired behavior

If the only available data is the daily endpoint, the system should state that it can only summarize the current 24-hour digest. If the weekly endpoint exists, the newsletter generator should call that endpoint instead and produce a true weekly brief.
