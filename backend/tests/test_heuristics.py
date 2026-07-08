"""Tests for the deterministic keyword/date fallback classifier, used only
when the local Ollama server is unreachable. This is the thing that silently
absorbed 191 failed classifications earlier in the project's history
(gpt-oss:20b producing garbled output) -- worth pinning down precisely
since it's the safety net for exactly that kind of outage.
"""

from datetime import timedelta

from app.ai.heuristics import heuristic_classification
from app.archive import now_utc

TODAY = now_utc().date()


def days_from_now(n: int):
    return TODAY + timedelta(days=n)


class TestHeuristicClassification:
    def test_always_marks_low_confidence_and_requires_human_review(self):
        result = heuristic_classification("Plain title", "plain body text", None)
        assert result["confidence"] == "low"
        assert result["human_review_required"] is True

    def test_baseline_scores_with_no_keyword_matches(self):
        result = heuristic_classification("Untitled", "nothing notable here", None)
        assert result["importance_score"] == 2
        assert result["transparency_risk_score"] == 1
        assert result["urgency_score"] == 2

    def test_importance_keywords_accumulate(self):
        result = heuristic_classification(None, "this ordinance proposes a rezoning near the coastal zone", None)
        # base 2 + ordinance(3) + rezoning(3) + coastal(3) = 11, clamped to 10
        assert result["importance_score"] == 10

    def test_transparency_keywords_accumulate(self):
        result = heuristic_classification(None, "supplemental packet posted before the closed session", None)
        # base 1 + supplemental packet(3) + closed session(2) = 6
        assert result["transparency_risk_score"] == 6

    def test_scores_are_clamped_to_10_not_allowed_to_exceed_it(self):
        text = "ordinance rezoning rezone general plan housing element coastal ceqa water rate lawsuit litigation"
        result = heuristic_classification(None, text, None)
        assert result["importance_score"] == 10

    def test_scores_are_clamped_to_a_minimum_of_0(self):
        # Every score has a positive base (2, 1, 2) so this mostly checks
        # _clamp's floor doesn't get bypassed; still worth asserting no
        # negative score can ever surface.
        result = heuristic_classification(None, "", None)
        assert result["importance_score"] >= 0
        assert result["transparency_risk_score"] >= 0
        assert result["urgency_score"] >= 0

    def test_title_is_included_in_keyword_search_not_just_body(self):
        result = heuristic_classification("Urgency Ordinance No. 5", "routine text", None)
        assert result["transparency_risk_score"] == 1 + 3  # "urgency ordinance" keyword

    def test_keyword_matching_is_case_insensitive(self):
        result = heuristic_classification(None, "THIS ORDINANCE IS IMPORTANT", None)
        assert result["importance_score"] > 2

    def test_no_meeting_date_gives_baseline_urgency(self):
        result = heuristic_classification(None, "text", None)
        assert result["urgency_score"] == 2

    def test_meeting_2_days_out_gives_urgency_9(self):
        result = heuristic_classification(None, "text", days_from_now(2))
        assert result["urgency_score"] == 9

    def test_meeting_7_days_out_gives_urgency_7(self):
        result = heuristic_classification(None, "text", days_from_now(7))
        assert result["urgency_score"] == 7

    def test_meeting_21_days_out_gives_urgency_5(self):
        result = heuristic_classification(None, "text", days_from_now(21))
        assert result["urgency_score"] == 5

    def test_meeting_22_days_out_falls_back_to_baseline_urgency(self):
        result = heuristic_classification(None, "text", days_from_now(22))
        assert result["urgency_score"] == 2

    def test_meeting_boundary_at_exactly_3_days_out_is_urgency_7_not_9(self):
        # days_out<=2 -> 9, days_out<=7 -> 7: 3 days out should land in the
        # second bucket, not the first.
        result = heuristic_classification(None, "text", days_from_now(3))
        assert result["urgency_score"] == 7

    def test_past_meeting_date_still_scores_maximum_urgency(self):
        # days_out is negative, which satisfies <=2 -- a meeting that
        # already happened reads as maximally urgent under this heuristic
        # (it doesn't special-case the past).
        result = heuristic_classification(None, "text", days_from_now(-5))
        assert result["urgency_score"] == 9

    def test_topics_default_to_general_governance_when_nothing_matches(self):
        result = heuristic_classification(None, "nothing topical here", None)
        assert result["topic_categories"] == ["general_governance"]

    def test_topics_are_derived_from_keyword_matches(self):
        result = heuristic_classification(None, "a proposal to rezone housing near the coast", None)
        assert "zoning" in result["topic_categories"]
        assert "housing" in result["topic_categories"]

    def test_topics_are_capped_at_three_even_with_many_matches(self):
        text = "coastal hillside housing zoning ceqa election campaign budget water"
        result = heuristic_classification(None, text, None)
        assert len(result["topic_categories"]) == 3

    def test_topics_list_is_sorted_and_deduplicated(self):
        # "rezone" and "zoning" both map to the same "zoning" topic --
        # should appear once, and the overall list should be sorted.
        result = heuristic_classification(None, "rezone zoning proposal", None)
        assert result["topic_categories"].count("zoning") == 1
        assert result["topic_categories"] == sorted(result["topic_categories"])

    def test_public_hearing_phrase_sets_hearing_and_participation_flags(self):
        result = heuristic_classification(None, "a public hearing will be held", None)
        assert result["hearing_expected"] is True
        assert result["public_participation_opportunity"] is True

    def test_public_comment_phrase_sets_participation_flag_but_not_hearing(self):
        result = heuristic_classification(None, "a public comment period is open", None)
        assert result["public_participation_opportunity"] is True
        assert result["hearing_expected"] is False

    def test_vote_expected_triggers_on_any_of_its_keywords(self):
        for phrase in ("staff recommends the board adopt", "council will approve", "resolution no. 26-01", "ordinance no. 5"):
            result = heuristic_classification(None, phrase, None)
            assert result["vote_expected"] is True, phrase

    def test_vote_expected_is_false_with_no_matching_language(self):
        result = heuristic_classification(None, "an informational item with no action requested", None)
        assert result["vote_expected"] is False
