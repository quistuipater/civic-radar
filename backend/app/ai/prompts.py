"""Versioned prompt templates (prd.md 10.3). Defaults live here as code; they're
seeded into the `prompts` table so every ai_outputs row can trace back to the
exact prompt_text/model/version that produced it.
"""

TOPIC_TAXONOMY = [
    "land_use", "planning", "zoning", "coastal_development", "hillside_development",
    "housing", "ceqa_environment", "public_notice_transparency", "elections",
    "campaign_finance", "budget_tax_fees", "water", "transportation",
    "police_public_safety", "homelessness", "schools", "parks_open_space",
    "cannabis", "short_term_rentals", "public_contracts", "appointments_commissions",
    "litigation", "ethics_conflict_of_interest", "infrastructure", "general_governance",
]

CLASSIFICATION_PROMPT = """You are a civic-affairs classification assistant for Ventura Civic Radar.
Classify the following government document/agenda item. Be conservative: never assert
corruption, illegality, or bad faith unless the text explicitly says so. Treat anything
you are not confident about as low confidence and set human_review_required to true.

Allowed topic_categories (choose 1-3): {taxonomy}

Document title: {title}
Jurisdiction: {jurisdiction}
Agency/body: {agency}
Meeting date: {meeting_date}

Text:
---
{text}
---

Respond with ONLY a JSON object matching this exact shape:
{{
  "topic_categories": ["..."],
  "importance_score": 0,
  "urgency_score": 0,
  "transparency_risk_score": 0,
  "public_participation_opportunity": false,
  "vote_expected": false,
  "hearing_expected": false,
  "human_review_required": false,
  "confidence": "low|medium|high",
  "rationale": "one or two sentences, grounded only in the text above"
}}
Scores are 0-10 integers per the scale: 0-2 routine, 3-5 moderate, 6-8 significant, 9-10 major/imminent.
"""

SUMMARY_PROMPT = """You are drafting a plain-English document summary for Ventura Civic Radar,
a civic-intelligence tool for a columnist/analyst. Distinguish source facts from inference.
Never invent dates, names, or figures that are not present in the text below.

Document title: {title}
Jurisdiction: {jurisdiction}

Text:
---
{text}
---

Respond with ONLY a JSON object matching this exact shape:
{{
  "plain_english_summary": "...",
  "key_decision_requested": "...",
  "what_changes_from_current_policy": "...",
  "who_is_affected": "...",
  "dates_and_deadlines": "...",
  "staff_recommendation": "...",
  "potential_controversy": "...",
  "source_confidence": "low|medium|high"
}}
"""

MEETING_RESULTS_PROMPT = """You are summarizing what actually happened at a government meeting, from its
minutes, for Ventura Civic Radar. This is about *outcomes* (what was decided), not what was proposed --
do not restate the agenda. Distinguish source facts from inference; never invent a vote tally, name, or
outcome that isn't stated in the text. Be conservative: never assert corruption, illegality, or bad faith
unless the text explicitly says so. If a field isn't stated, use null rather than guessing.

Jurisdiction: {jurisdiction}
Agency/body: {agency}
Meeting date: {meeting_date}

Minutes text:
---
{text}
---

Respond with ONLY a JSON object matching this exact shape:
{{
  "overall_summary": "plain-English account of what happened at this meeting, 2-4 sentences",
  "key_decisions": [
    {{
      "topic": "what the decision was about",
      "outcome": "approved|denied|continued|withdrawn|no_action|other",
      "vote_tally": "e.g. '4-1' or null if not stated",
      "notes": "brief context -- dissent, conditions attached, notable discussion"
    }}
  ],
  "notable_public_comment": "themes raised in public comment, or null if none/not recorded",
  "continued_or_tabled_items": "items pushed to a future meeting, or null if none",
  "source_confidence": "low|medium|high"
}}
If nothing decision-worthy happened (e.g. a cancelled meeting), respond with key_decisions: [].
"""

AGENDA_ITEM_EXTRACTION_PROMPT = """You are splitting a government meeting agenda into its individual agenda items
for Ventura Civic Radar. Skip non-substantive entries (call to order, roll call, pledge, adjournment,
public comment period headers). Be conservative: never assert corruption, illegality, or bad faith. If a
field isn't stated in the text, use null rather than guessing.

Jurisdiction: {jurisdiction}
Agency/body: {agency}
Meeting date: {meeting_date}

Agenda text:
---
{text}
---

Respond with ONLY a JSON object matching this exact shape:
{{
  "items": [
    {{
      "item_number": "...",
      "title": "...",
      "description": "...",
      "department": "...",
      "staff_recommendation": "...",
      "action_type": "consent|discussion|action|public_hearing|presentation|closed_session",
      "consent_calendar": false,
      "public_hearing": false,
      "vote_expected": false
    }}
  ]
}}
If no substantive items are found, respond with {{"items": []}}.
"""

PROMPT_DEFAULTS = [
    dict(
        prompt_key="agenda_item_classification",
        prompt_version="v1",
        task_type="classification",
        prompt_text=CLASSIFICATION_PROMPT,
        model_name=None,  # filled from settings at seed time
        model_params={"temperature": 0.1},
        json_schema={
            "topic_categories": "list[str]",
            "importance_score": "int",
            "urgency_score": "int",
            "transparency_risk_score": "int",
            "public_participation_opportunity": "bool",
            "vote_expected": "bool",
            "hearing_expected": "bool",
            "human_review_required": "bool",
            "confidence": "str",
            "rationale": "str",
        },
        active=True,
    ),
    dict(
        prompt_key="document_summary",
        prompt_version="v1",
        task_type="summarization",
        prompt_text=SUMMARY_PROMPT,
        model_name=None,
        model_params={"temperature": 0.2},
        json_schema={
            "plain_english_summary": "str",
            "key_decision_requested": "str",
            "what_changes_from_current_policy": "str",
            "who_is_affected": "str",
            "dates_and_deadlines": "str",
            "staff_recommendation": "str",
            "potential_controversy": "str",
            "source_confidence": "str",
        },
        active=True,
    ),
    dict(
        prompt_key="agenda_item_extraction",
        prompt_version="v1",
        task_type="agenda_item_extraction",
        prompt_text=AGENDA_ITEM_EXTRACTION_PROMPT,
        model_name=None,
        model_params={"temperature": 0.1},
        json_schema={
            "items": [
                {
                    "item_number": "str",
                    "title": "str",
                    "description": "str",
                    "department": "str",
                    "staff_recommendation": "str",
                    "action_type": "str",
                    "consent_calendar": "bool",
                    "public_hearing": "bool",
                    "vote_expected": "bool",
                }
            ]
        },
        active=True,
    ),
    dict(
        prompt_key="meeting_results_summary",
        prompt_version="v1",
        task_type="meeting_results_summary",
        prompt_text=MEETING_RESULTS_PROMPT,
        model_name=None,
        model_params={"temperature": 0.2},
        json_schema={
            "overall_summary": "str",
            "key_decisions": [
                {"topic": "str", "outcome": "str", "vote_tally": "str", "notes": "str"}
            ],
            "notable_public_comment": "str",
            "continued_or_tabled_items": "str",
            "source_confidence": "str",
        },
        active=True,
    ),
]
