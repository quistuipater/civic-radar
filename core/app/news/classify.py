"""Classifies news articles against the shared civic-topic ontology
(app.ai.prompts.TOPIC_TAXONOMY). Heuristic keyword matching runs first and
covers the common case cheaply; the AI fallback (same Ollama client as
ai/classify.py) only fires when the heuristic finds nothing, keeping
steady-state inference load low at news volume.
"""

import re

from app.ai import ollama_client
from app.ai.prompts import NEWS_CLASSIFICATION_PROMPT, TOPIC_TAXONOMY
from app.config import settings

NEWS_TOPIC_KEYWORDS: dict[str, list[str]] = {
    "land_use": ["land use", "land-use", "general plan", "specific plan"],
    "planning": ["planning commission", "planning department", "site plan", "development plan"],
    "zoning": ["zoning", "rezone", "rezoning", "zone change", "variance"],
    "coastal_development": ["coastal commission", "coastal development permit", "coastal zone", "shoreline"],
    "hillside_development": ["hillside development", "hillside ordinance", "ridgeline"],
    "housing": ["housing", "affordable housing", "apartment complex", "housing element"],
    "ceqa_environment": ["ceqa", "environmental impact report", "environmental review"],
    "public_notice_transparency": ["public records act", "brown act", "public notice", "transparency"],
    "elections": ["election", "ballot measure", "candidate filing", "voter", "primary election"],
    "campaign_finance": ["campaign finance", "campaign contribution", "fppc", "netfile", "campaign donor"],
    "budget_tax_fees": ["city budget", "county budget", "property tax", "sales tax", "budget deficit", "fee increase"],
    "water": ["water district", "water supply", "drought", "water rate", "groundwater"],
    "transportation": ["transportation", "traffic", "bike lane", "metrolink", "vcta", "highway 101", "freeway"],
    "police_public_safety": ["police", "sheriff", "arrest", "crime", "public safety", "fire department"],
    "homelessness": ["homeless", "homelessness", "unhoused", "encampment"],
    "schools": ["school district", "school board", "unified school", "superintendent"],
    "parks_open_space": ["park", "open space", "trail", "recreation area"],
    "cannabis": ["cannabis", "marijuana", "dispensary"],
    "short_term_rentals": ["short-term rental", "short term rental", "airbnb", "vacation rental", "stvr"],
    "public_contracts": ["public contract", "bid award", "request for proposal", "procurement", "contract award"],
    "appointments_commissions": ["appointed to", "commission appointment", "board appointment", "sworn in"],
    "litigation": ["lawsuit", "litigation", "sues", "sued", "legal settlement", "court ruling"],
    "ethics_conflict_of_interest": ["conflict of interest", "ethics complaint", "ethics commission", "recusal"],
    "infrastructure": ["infrastructure", "sewer", "road repair", "bridge", "utility", "pipeline"],
    "general_governance": ["city council", "board of supervisors", "city clerk", "ordinance", "resolution"],
}


def heuristic_classify_article(title: str, summary: str | None, full_text: str | None) -> list[str]:
    haystack = " ".join(filter(None, [title, summary, full_text])).lower()
    scores: dict[str, int] = {}
    for category, keywords in NEWS_TOPIC_KEYWORDS.items():
        if category not in TOPIC_TAXONOMY:
            continue
        count = sum(1 for kw in keywords if re.search(rf"\b{re.escape(kw)}\b", haystack))
        if count:
            scores[category] = count
    ranked = sorted(scores.items(), key=lambda pair: pair[1], reverse=True)
    return [category for category, _ in ranked[:3]]


def classify_article(title: str, summary: str | None, full_text: str | None) -> tuple[list[str], str, str]:
    """Returns (topic_categories, classification_method, classification_confidence)."""
    categories = heuristic_classify_article(title, summary, full_text)
    if categories:
        return categories, "heuristic", "medium"

    if not ollama_client.is_available():
        return [], "heuristic", "low"

    text = "\n\n".join(filter(None, [summary, full_text]))
    prompt = NEWS_CLASSIFICATION_PROMPT.format(
        project_name=settings.project_name,
        taxonomy=", ".join(TOPIC_TAXONOMY),
        title=title,
        text=text[:8000],
    )
    output_json, _error = ollama_client.generate_json(settings.ollama_triage_model, prompt)
    if not output_json:
        return [], "heuristic", "low"

    ai_categories = [c for c in output_json.get("topic_categories") or [] if c in TOPIC_TAXONOMY][:3]
    if not ai_categories:
        return [], "heuristic", "low"
    return ai_categories, "ai", "high"
