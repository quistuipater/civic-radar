"""Phase-0 issue clustering (prd.md 9.11): match a newly parsed document to an
existing issue.

Auto-link only happens on exact identifier overlap (project/ordinance/
resolution number), confidence="high" -- unchanged from before.

Fuzzy semantic matching via document_chunks.embedding is suggestion-only, not
auto-link: `suggest_issues_for_document()` returns ranked candidates for a
human to confirm via the existing POST /api/issues/{id}/links endpoint. It
does NOT create IssueLink rows itself. This was deliberate after testing an
auto-link version: today's issue-linked documents are often whole multi-topic
meeting packets (an exact-match link points at the *document* containing the
matching ordinance/project number, not a specific agenda_item), so their
mean-pooled chunk embeddings carry a lot of generic meeting-boilerplate signal
alongside the actual topic. Verified live 2026-07-06 against the one real
issue in this DB ("Downtown Parking Ordinance"): a broad sample of 80
unrelated documents (Design Review Committee, Economic Development
Subcommittee, Director's Hearing, etc.) fuzzy-"matched" at a 72/80 rate at a
threshold that looked reasonable on a 2-document spot check. Whole-document
embeddings just aren't discriminative enough in this corpus for unsupervised
auto-linking -- revisit once agenda_items carry their own (narrower,
single-topic) embeddings, or once there's a larger set of real issues to
calibrate a threshold against.
"""

from sqlalchemy.orm import Session

from app.models import Document, DocumentChunk, Issue, IssueLink

IDENTIFIER_FIELDS = ("project_number", "ordinance_number", "resolution_number")


def match_document_to_issue(db: Session, document: Document) -> Issue | None:
    for field in IDENTIFIER_FIELDS:
        value = getattr(document, field)
        if not value:
            continue

        sibling = (
            db.query(Document)
            .filter(getattr(Document, field) == value, Document.id != document.id)
            .join(IssueLink, IssueLink.document_id == Document.id)
            .first()
        )
        if sibling is None:
            continue

        link = db.query(IssueLink).filter(IssueLink.document_id == sibling.id).first()
        if link is None or link.issue_id is None:
            continue

        issue = db.get(Issue, link.issue_id)
        if issue is None:
            continue

        already_linked = (
            db.query(IssueLink)
            .filter(IssueLink.issue_id == issue.id, IssueLink.document_id == document.id)
            .one_or_none()
        )
        if already_linked is None:
            db.add(
                IssueLink(
                    issue_id=issue.id,
                    document_id=document.id,
                    relationship_type=f"matched_{field}",
                    confidence="high",
                    created_by="system",
                )
            )
            db.commit()
        return issue

    return None


def suggest_issues_for_document(db: Session, document: Document, limit: int = 5) -> list[dict]:
    """Ranked fuzzy-match candidates for a human to review -- never auto-linked.
    Returns [{issue, distance}], nearest first, capped at `limit`.
    """
    fingerprint = _document_fingerprint(db, document.id)
    if fingerprint is None:
        return []

    already_linked_issue_ids = {
        row[0]
        for row in db.query(IssueLink.issue_id).filter(IssueLink.document_id == document.id).all()
    }

    distance = DocumentChunk.embedding.cosine_distance(fingerprint).label("distance")
    rows = (
        db.query(IssueLink.issue_id, distance)
        .join(DocumentChunk, DocumentChunk.document_id == IssueLink.document_id)
        .filter(DocumentChunk.embedding.isnot(None), IssueLink.document_id != document.id)
        .order_by(distance)
        .limit(limit * 4)  # over-fetch since multiple rows can share an issue_id
        .all()
    )

    suggestions: list[dict] = []
    seen_issue_ids: set = set(already_linked_issue_ids)
    for issue_id, dist in rows:
        if issue_id in seen_issue_ids:
            continue
        seen_issue_ids.add(issue_id)
        issue = db.get(Issue, issue_id)
        if issue is None:
            continue
        suggestions.append({"issue": issue, "distance": float(dist)})
        if len(suggestions) >= limit:
            break
    return suggestions


def _document_fingerprint(db: Session, document_id) -> list[float] | None:
    """Mean of a document's own chunk embeddings -- a document-level vector for
    fuzzy matching, so the comparison isn't biased toward whichever single
    chunk (e.g. a title page) happens to get queried.
    """
    rows = (
        db.query(DocumentChunk.embedding)
        .filter(DocumentChunk.document_id == document_id, DocumentChunk.embedding.isnot(None))
        .all()
    )
    if not rows:
        return None
    vectors = [list(row[0]) for row in rows]
    dim = len(vectors[0])
    return [sum(v[i] for v in vectors) / len(vectors) for i in range(dim)]
