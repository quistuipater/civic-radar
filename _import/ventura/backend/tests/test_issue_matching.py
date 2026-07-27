"""Tests for issue clustering: exact-identifier auto-linking (confidence
"high") and embedding-based fuzzy suggestions (never auto-linked -- see the
module docstring for why: an earlier auto-link version fuzzy-"matched" 72/80
clearly unrelated documents in a live test, since whole-document mean-pooled
embeddings are dominated by generic meeting boilerplate). These tests pin
down both paths precisely, especially the suggestion ranking/dedup/exclusion
logic that has no other coverage.
"""

from app.issue_matching import _document_fingerprint, match_document_to_issue, suggest_issues_for_document
from app.models import DocumentChunk, IssueLink

from .conftest import make_document, make_issue


def link_document_to_issue(db, document, issue, **overrides):
    defaults = dict(document_id=document.id, issue_id=issue.id, relationship_type="manual", confidence="operator")
    defaults.update(overrides)
    link = IssueLink(**defaults)
    db.add(link)
    db.flush()
    return link


def add_chunk(db, document, embedding, chunk_index=0):
    chunk = DocumentChunk(
        document_id=document.id, chunk_index=chunk_index, text=f"chunk {chunk_index} text", embedding=embedding
    )
    db.add(chunk)
    db.flush()
    return chunk


VEC_A = [0.1] * 768
VEC_A_CLOSE = [0.1] * 767 + [0.11]  # nearly identical to VEC_A
VEC_B = [0.9] * 384 + [0.1] * 384  # very different direction from VEC_A


class TestMatchDocumentToIssue:
    def test_no_identifier_fields_set_returns_none(self, db):
        document = make_document(db, project_number=None, ordinance_number=None, resolution_number=None)
        db.commit()

        assert match_document_to_issue(db, document) is None

    def test_matching_project_number_auto_links_with_high_confidence(self, db):
        issue = make_issue(db)
        linked_doc = make_document(db, project_number="PL26-0042")
        link_document_to_issue(db, linked_doc, issue)
        new_doc = make_document(db, project_number="PL26-0042")
        db.commit()

        result = match_document_to_issue(db, new_doc)

        assert result.id == issue.id
        created_link = db.query(IssueLink).filter_by(document_id=new_doc.id).one()
        assert created_link.confidence == "high"
        assert created_link.relationship_type == "matched_project_number"
        assert created_link.created_by == "system"

    def test_matching_ordinance_number_auto_links(self, db):
        issue = make_issue(db)
        linked_doc = make_document(db, ordinance_number="ORD-2026-05")
        link_document_to_issue(db, linked_doc, issue)
        new_doc = make_document(db, ordinance_number="ORD-2026-05")
        db.commit()

        result = match_document_to_issue(db, new_doc)

        assert result.id == issue.id
        assert db.query(IssueLink).filter_by(document_id=new_doc.id).one().relationship_type == "matched_ordinance_number"

    def test_matching_resolution_number_auto_links(self, db):
        issue = make_issue(db)
        linked_doc = make_document(db, resolution_number="RES-2026-12")
        link_document_to_issue(db, linked_doc, issue)
        new_doc = make_document(db, resolution_number="RES-2026-12")
        db.commit()

        result = match_document_to_issue(db, new_doc)

        assert result.id == issue.id

    def test_project_number_is_checked_before_ordinance_number(self, db):
        # IDENTIFIER_FIELDS order is (project_number, ordinance_number,
        # resolution_number) -- a document matching on project_number should
        # never fall through to check ordinance_number against a different
        # issue.
        project_issue = make_issue(db, slug="project-issue")
        ordinance_issue = make_issue(db, slug="ordinance-issue")
        link_document_to_issue(db, make_document(db, project_number="PL26-0042"), project_issue)
        link_document_to_issue(db, make_document(db, ordinance_number="ORD-2026-05"), ordinance_issue)
        new_doc = make_document(db, project_number="PL26-0042", ordinance_number="ORD-2026-05")
        db.commit()

        result = match_document_to_issue(db, new_doc)

        assert result.id == project_issue.id

    def test_sibling_with_same_identifier_but_not_linked_to_any_issue_does_not_match(self, db):
        make_document(db, project_number="PL26-0042")  # sibling exists, no IssueLink at all
        new_doc = make_document(db, project_number="PL26-0042")
        db.commit()

        assert match_document_to_issue(db, new_doc) is None

    def test_rerunning_against_an_already_linked_document_does_not_create_a_duplicate_link(self, db):
        issue = make_issue(db)
        linked_doc = make_document(db, project_number="PL26-0042")
        link_document_to_issue(db, linked_doc, issue)
        new_doc = make_document(db, project_number="PL26-0042")
        db.commit()

        first = match_document_to_issue(db, new_doc)
        second = match_document_to_issue(db, new_doc)

        assert first.id == second.id == issue.id
        assert db.query(IssueLink).filter_by(document_id=new_doc.id).count() == 1


class TestDocumentFingerprint:
    def test_returns_none_when_document_has_no_chunks(self, db):
        document = make_document(db)
        db.commit()

        assert _document_fingerprint(db, document.id) is None

    def test_returns_none_when_chunks_have_no_embeddings(self, db):
        document = make_document(db)
        add_chunk(db, document, embedding=None)
        db.commit()

        assert _document_fingerprint(db, document.id) is None

    def test_single_chunk_fingerprint_equals_its_embedding(self, db):
        document = make_document(db)
        add_chunk(db, document, embedding=VEC_A)
        db.commit()

        fingerprint = _document_fingerprint(db, document.id)
        assert fingerprint == list(VEC_A)

    def test_multiple_chunks_fingerprint_is_the_mean(self, db):
        document = make_document(db)
        add_chunk(db, document, embedding=[0.0] * 768, chunk_index=0)
        add_chunk(db, document, embedding=[2.0] * 768, chunk_index=1)
        db.commit()

        fingerprint = _document_fingerprint(db, document.id)
        assert fingerprint == [1.0] * 768


class TestSuggestIssuesForDocument:
    def test_returns_empty_list_when_document_has_no_embeddings(self, db):
        document = make_document(db)
        db.commit()
        assert suggest_issues_for_document(db, document) == []

    def test_returns_empty_list_when_no_other_documents_are_linked_to_any_issue(self, db):
        document = make_document(db)
        add_chunk(db, document, embedding=VEC_A)
        db.commit()
        assert suggest_issues_for_document(db, document) == []

    def test_suggests_the_issue_of_a_similar_linked_document(self, db):
        issue = make_issue(db)
        linked_doc = make_document(db)
        add_chunk(db, linked_doc, embedding=VEC_A)
        link_document_to_issue(db, linked_doc, issue)

        target = make_document(db)
        add_chunk(db, target, embedding=VEC_A_CLOSE)
        db.commit()

        suggestions = suggest_issues_for_document(db, target)

        assert len(suggestions) == 1
        assert suggestions[0]["issue"].id == issue.id
        assert suggestions[0]["distance"] < 0.01

    def test_nearer_candidate_is_ranked_first(self, db):
        near_issue = make_issue(db, slug="near-issue")
        far_issue = make_issue(db, slug="far-issue")
        near_doc = make_document(db)
        add_chunk(db, near_doc, embedding=VEC_A_CLOSE)
        link_document_to_issue(db, near_doc, near_issue)
        far_doc = make_document(db)
        add_chunk(db, far_doc, embedding=VEC_B)
        link_document_to_issue(db, far_doc, far_issue)

        target = make_document(db)
        add_chunk(db, target, embedding=VEC_A)
        db.commit()

        suggestions = suggest_issues_for_document(db, target)

        assert [s["issue"].id for s in suggestions] == [near_issue.id, far_issue.id]

    def test_already_linked_issue_is_excluded_from_suggestions(self, db):
        issue = make_issue(db)
        linked_doc = make_document(db)
        add_chunk(db, linked_doc, embedding=VEC_A)
        link_document_to_issue(db, linked_doc, issue)

        target = make_document(db)
        add_chunk(db, target, embedding=VEC_A_CLOSE)
        link_document_to_issue(db, target, issue)  # target is already linked to this same issue
        db.commit()

        assert suggest_issues_for_document(db, target) == []

    def test_multiple_chunks_from_the_same_issue_do_not_produce_duplicate_suggestions(self, db):
        issue = make_issue(db)
        linked_doc = make_document(db)
        add_chunk(db, linked_doc, embedding=VEC_A, chunk_index=0)
        add_chunk(db, linked_doc, embedding=VEC_A_CLOSE, chunk_index=1)
        link_document_to_issue(db, linked_doc, issue)

        target = make_document(db)
        add_chunk(db, target, embedding=VEC_A)
        db.commit()

        suggestions = suggest_issues_for_document(db, target)

        assert len(suggestions) == 1

    def test_results_are_capped_at_the_requested_limit(self, db):
        target = make_document(db)
        add_chunk(db, target, embedding=VEC_A)
        for i in range(5):
            issue = make_issue(db, slug=f"issue-{i}")
            doc = make_document(db)
            add_chunk(db, doc, embedding=VEC_A_CLOSE)
            link_document_to_issue(db, doc, issue)
        db.commit()

        suggestions = suggest_issues_for_document(db, target, limit=2)

        assert len(suggestions) == 2

    def test_the_target_documents_own_chunks_are_not_matched_against_themselves(self, db):
        # target is linked to no issue, but even if it somehow were its own
        # "sibling", the query explicitly excludes IssueLink.document_id ==
        # document.id -- this guards that exclusion.
        issue = make_issue(db)
        target = make_document(db)
        add_chunk(db, target, embedding=VEC_A)
        link_document_to_issue(db, target, issue)
        db.commit()

        assert suggest_issues_for_document(db, target) == []
