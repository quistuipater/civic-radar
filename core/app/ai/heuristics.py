"""Deterministic keyword/date fallback used only when the local model server is
unavailable, so the pipeline still produces *some* triage signal instead of
nulls. Always marked low-confidence + human_review_required, per prd.md's
guardrail that low-confidence-but-high-importance items must reach review.
"""

from datetime import date, datetime, timezone

IMPORTANCE_KEYWORDS = {
    "ordinance": 3, "rezone": 3, "rezoning": 3, "general plan": 3, "housing element": 3,
    "coastal": 3, "ceqa": 2, "environmental impact": 2, "budget": 2, "tax": 2,
    "fee increase": 2, "water rate": 3, "appeal": 2, "lawsuit": 3, "litigation": 3,
}

TRANSPARENCY_KEYWORDS = {
    "supplemental packet": 3, "closed session": 2, "special meeting": 2,
    "notice": 1, "consent calendar": 2, "continued": 1, "urgency ordinance": 3,
}

TOPIC_KEYWORDS = {
    "coastal": "coastal_development", "hillside": "hillside_development",
    "housing": "housing", "zoning": "zoning", "rezone": "zoning",
    "ceqa": "ceqa_environment", "environmental impact": "ceqa_environment",
    "notice": "public_notice_transparency", "election": "elections",
    "campaign": "campaign_finance", "budget": "budget_tax_fees", "tax": "budget_tax_fees",
    "fee": "budget_tax_fees", "water": "water", "transportation": "transportation",
    "traffic": "transportation", "police": "police_public_safety",
    "public safety": "police_public_safety", "homeless": "homelessness",
    "school": "schools", "park": "parks_open_space", "cannabis": "cannabis",
    "short-term rental": "short_term_rentals", "str permit": "short_term_rentals",
    "contract": "public_contracts", "appoint": "appointments_commissions",
    "litigation": "litigation", "lawsuit": "litigation",
    "conflict of interest": "ethics_conflict_of_interest", "ethics": "ethics_conflict_of_interest",
    "infrastructure": "infrastructure", "sewer": "infrastructure", "road": "infrastructure",
    "planning commission": "planning", "land use": "land_use",
}


def _clamp(value: int) -> int:
    return max(0, min(10, value))


def heuristic_classification(title: str | None, text: str, meeting_date: date | None) -> dict:
    haystack = f"{title or ''}\n{text}".lower()

    importance = 2 + sum(weight for kw, weight in IMPORTANCE_KEYWORDS.items() if kw in haystack)
    transparency = 1 + sum(weight for kw, weight in TRANSPARENCY_KEYWORDS.items() if kw in haystack)

    urgency = 2
    if meeting_date:
        days_out = (meeting_date - datetime.now(timezone.utc).date()).days
        if days_out <= 2:
            urgency = 9
        elif days_out <= 7:
            urgency = 7
        elif days_out <= 21:
            urgency = 5

    topics = sorted({topic for kw, topic in TOPIC_KEYWORDS.items() if kw in haystack})
    if not topics:
        topics = ["general_governance"]

    return {
        "topic_categories": topics[:3],
        "importance_score": _clamp(importance),
        "urgency_score": _clamp(urgency),
        "transparency_risk_score": _clamp(transparency),
        "public_participation_opportunity": "public hearing" in haystack or "public comment" in haystack,
        "vote_expected": any(w in haystack for w in ("adopt", "approve", "resolution no", "ordinance no")),
        "hearing_expected": "public hearing" in haystack,
        "human_review_required": True,
        "confidence": "low",
        "rationale": "Heuristic keyword/date fallback — local AI model server was unavailable at classification time.",
    }
