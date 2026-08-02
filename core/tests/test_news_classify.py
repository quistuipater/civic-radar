"""Tests for classify_article -- heuristic keyword matching runs first;
the AI fallback (same Ollama client as ai/classify.py) only fires when the
heuristic finds nothing. Confidence values follow a fixed rule (see the
design doc): heuristic match -> "medium", successful AI fallback -> "high",
empty/unavailable -> "low".
"""

import app.news.classify as classify_module
from app.news.classify import classify_article, heuristic_classify_article


class TestHeuristicClassifyArticle:
    def test_matches_zoning_keywords(self):
        categories = heuristic_classify_article(
            "City Council Approves New Zoning Rules", "The council voted on a zoning variance.", None
        )

        assert "zoning" in categories

    def test_matches_multiple_categories_ranked_by_hit_count(self):
        categories = heuristic_classify_article(
            "Police Respond to Homeless Encampment Near School",
            "Sheriff deputies and school district officials met about the homeless encampment.",
            None,
        )

        assert "police_public_safety" in categories
        assert "homelessness" in categories
        assert "schools" in categories

    def test_returns_empty_for_unrelated_article(self):
        categories = heuristic_classify_article(
            "Local Bakery Wins National Award", "The bakery's sourdough took first place.", None
        )

        assert categories == []

    def test_considers_full_text_not_just_title_and_summary(self):
        categories = heuristic_classify_article(
            "Community Event This Weekend", "Join us Saturday.", "The event follows the city's new short-term rental ordinance."
        )

        assert "short_term_rentals" in categories

    def test_filters_categories_not_in_taxonomy(self, monkeypatch):
        """Ensure heuristic path validates against TOPIC_TAXONOMY, same as AI path.
        Simulates a stale keyword entry not in the taxonomy by adding a fake category.
        """
        stale_keywords = classify_module.NEWS_TOPIC_KEYWORDS.copy()
        stale_keywords["stale_removed_category"] = ["zoning", "rezone"]  # Would match but shouldn't be returned
        monkeypatch.setattr(classify_module, "NEWS_TOPIC_KEYWORDS", stale_keywords)

        categories = heuristic_classify_article(
            "City Council Approves New Zoning Rules", "A zoning variance was granted.", None
        )

        # Should return "zoning" (valid taxonomy entry) but NOT "stale_removed_category"
        assert "zoning" in categories
        assert "stale_removed_category" not in categories

    def test_does_not_match_substring_inside_a_different_word(self):
        categories = heuristic_classify_article(
            "The board discussed several issues at length.", None, None
        )

        assert "litigation" not in categories

    def test_does_not_match_pursued_as_sued(self):
        categories = heuristic_classify_article(
            "She pursued a career in baking.", None, None
        )

        assert "litigation" not in categories

    def test_does_not_match_parking_as_park(self):
        categories = heuristic_classify_article(
            "The new parking garage opens downtown.", None, None
        )

        assert "parks_open_space" not in categories

    def test_does_not_match_trailer_as_trail(self):
        categories = heuristic_classify_article(
            "A trailer overturned on the highway.", None, None
        )

        assert categories == []


class TestClassifyArticle:
    def test_returns_medium_confidence_when_heuristic_matches(self):
        categories, method, confidence = classify_article(
            "City Council Approves New Zoning Rules", "A zoning variance was granted.", None
        )

        assert categories
        assert method == "heuristic"
        assert confidence == "medium"

    def test_falls_back_to_ai_when_heuristic_finds_nothing(self, monkeypatch):
        monkeypatch.setattr(classify_module.ollama_client, "is_available", lambda: True)
        monkeypatch.setattr(
            classify_module.ollama_client,
            "generate_json",
            lambda model, prompt, **k: ({"topic_categories": ["general_governance"]}, None),
        )

        categories, method, confidence = classify_article("Local Bakery Wins Award", "A feel-good story.", None)

        assert categories == ["general_governance"]
        assert method == "ai"
        assert confidence == "high"

    def test_returns_low_confidence_when_ollama_unavailable(self, monkeypatch):
        monkeypatch.setattr(classify_module.ollama_client, "is_available", lambda: False)

        categories, method, confidence = classify_article("Local Bakery Wins Award", "A feel-good story.", None)

        assert categories == []
        assert method == "heuristic"
        assert confidence == "low"

    def test_returns_low_confidence_when_ollama_call_fails(self, monkeypatch):
        monkeypatch.setattr(classify_module.ollama_client, "is_available", lambda: True)
        monkeypatch.setattr(
            classify_module.ollama_client, "generate_json", lambda model, prompt, **k: (None, "connection refused")
        )

        categories, method, confidence = classify_article("Local Bakery Wins Award", "A feel-good story.", None)

        assert categories == []
        assert method == "heuristic"
        assert confidence == "low"

    def test_drops_ai_categories_not_in_taxonomy(self, monkeypatch):
        monkeypatch.setattr(classify_module.ollama_client, "is_available", lambda: True)
        monkeypatch.setattr(
            classify_module.ollama_client,
            "generate_json",
            lambda model, prompt, **k: ({"topic_categories": ["not_a_real_category"]}, None),
        )

        categories, method, confidence = classify_article("Local Bakery Wins Award", "A feel-good story.", None)

        assert categories == []
        assert method == "heuristic"
        assert confidence == "low"
