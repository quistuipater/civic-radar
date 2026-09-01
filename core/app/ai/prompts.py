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

CLASSIFICATION_PROMPT = """You are a civic-affairs classification assistant for {project_name}.
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

SUMMARY_PROMPT = """You are drafting a plain-English document summary for {project_name},
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
minutes, for {project_name}. This is about *outcomes* (what was decided), not what was proposed --
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
for {project_name}. Skip non-substantive entries (call to order, roll call, pledge, adjournment,
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

NEWS_CLASSIFICATION_PROMPT = """You are a civic-news classification assistant for {project_name}.
Classify the following local news article by which civic topics it covers, if any. Be
conservative: if the article is not meaningfully about local government or civic affairs
(e.g. sports, obituaries, entertainment, feel-good human interest), return an empty list
rather than forcing a fit.

Allowed topic_categories (choose 0-3): {taxonomy}

Article title: {title}

Text:
---
{text}
---

Respond with ONLY a JSON object matching this exact shape:
{{
  "topic_categories": ["..."]
}}
"""

ORG_ASSERTION_EXTRACTION_PROMPT = """You are extracting organizational-structure claims from a {project_name} \
government document, for a system that tracks who holds which position, which units exist, and how they report \
to each other over time. Extract only claims actually stated in the text -- never infer a personnel action \
(appointed, resigned, terminated, promoted, demoted) that the text doesn't explicitly state. A person's name \
appearing near a title is not itself proof of an appointment; only extract "occupies_position" if the text \
states or clearly implies that relationship (e.g. "Jane Smith, City Manager" on a roster, or "the Council \
appointed Jane Smith as City Manager").

Use predicate values ONLY from this list: occupies_position, member_of, reports_to_position, \
unit_reports_to_unit, appoints, oversees, part_of, succeeded_by.

For "occupies_position", subject_text is ALWAYS the person's name and object_text is ALWAYS the position \
title -- never the reverse. Roster text is often a repeating "Name, Title" pattern, sometimes with several \
such pairs run together on one line because the source document laid them out in columns that collapsed \
into flat text (e.g. a two-column attendee list flattened by PDF extraction). Read each "Name, Title" as one \
atomic pair in that left-to-right order; do not let a title word from one pair get attached to the name of \
the next pair. For example, the flattened line \
"Joe Schroeder, Mayor Meredith Hart, Economic Development Manager" contains TWO pairs -- (Joe Schroeder, \
Mayor) and (Meredith Hart, Economic Development Manager) -- not one pair "Mayor Meredith Hart". If you \
cannot confidently tell where one pair ends and the next begins, extract nothing for that ambiguous span \
rather than guessing a pairing, and prefer evidence_mode "inferred" or skipping over a swapped subject/object.

Not every claim involves a named person -- "appoints", "oversees", "reports_to_position", \
"unit_reports_to_unit", and "part_of" are often stated purely between roles/bodies/units, with no individual's \
name in the sentence at all. For example, the sentence "The City Council hires 2 of the principal officials \
of the City, the City Manager and the City Attorney" contains TWO valid "appoints" claims even though no \
person is named: (City Council, appoints, City Manager) and (City Council, appoints, City Attorney) -- \
subject_text and object_text here are role/body names ("City Council", "City Manager"), not people. Do not \
skip a clearly-stated institutional relationship just because it lacks a named individual.

evidence_mode must be one of: "explicit" (the text directly states this fact), "derived" (the text states \
something else that implies this, e.g. a vote result implies an appointment), "inferred" (a weaker inference \
you are less certain of -- prefer not extracting rather than inferring).

Document type: {document_type}
Jurisdiction: {jurisdiction}
Agency/body: {agency}

Document text:
---
{text}
---

Respond with ONLY a JSON object matching this exact shape:
{{
  "assertions": [
    {{
      "subject_text": "...",
      "predicate": "occupies_position",
      "object_text": "...",
      "assertion_type": "appointment|membership|reporting_line|unit_change|other",
      "effective_date": "YYYY-MM-DD or null",
      "evidence_mode": "explicit|derived|inferred",
      "quoted_passage": "the exact sentence or phrase supporting this claim",
      "confidence": "high|medium|low"
    }}
  ]
}}
If no organizational claims are found, respond with {{"assertions": []}}.
"""

NARRATIVE_SUMMARY_PROMPT = """You are writing the "Overview" section of a {period_label} civic-activity report \
for {project_name} covering {jurisdiction}, for the period {period_start} to {period_end}. Every other section \
of this report (stat counts, meeting lists, filing tables, alert log) is rendered separately from real query \
results -- your ONLY job is 2-3 short narrative paragraphs that give a reader the gist without reading every \
underlying document, using the real numbers below as your only facts.

These numbers are already correct and final -- restate them accurately, never recompute, round loosely, or \
invent additional ones. If a count is 0, say so plainly (e.g. "No new public notices this period") rather than \
omitting it or inventing activity. Distinguish clearly between something that already happened (a vote, a \
filing, a meeting held) and something merely scheduled or upcoming. Keep a neutral, factual, slightly formal \
tone -- this is a civic-monitoring report, not commentary or advocacy. Do not use markdown headers -- write \
plain paragraphs only (the surrounding report already has its own headers).

Real stats for this period:
---
{stats_summary}
---

Respond with ONLY a JSON object with EXACTLY these two keys, spelled exactly as shown -- "narrative_markdown" \
is the full field name, not "narrative" or any shortened/renamed version of it:
{{
  "title": "a short, specific headline for this period (e.g. 'Ventura: Quiet week, one hearing scheduled')",
  "narrative_markdown": "2-3 plain paragraphs (no markdown headers), each a normal paragraph of prose, using \
the real numbers above naturally in the text"
}}
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
    dict(
        prompt_key="org_assertion_extraction",
        prompt_version="v3",
        task_type="org_assertion_extraction",
        prompt_text=ORG_ASSERTION_EXTRACTION_PROMPT,
        model_name=None,
        model_params={"temperature": 0.1},
        json_schema={
            "assertions": [
                {
                    "subject_text": "str",
                    "predicate": "str",
                    "object_text": "str",
                    "assertion_type": "str",
                    "effective_date": "str|null",
                    "evidence_mode": "str",
                    "quoted_passage": "str",
                    "confidence": "str",
                }
            ]
        },
        active=True,
    ),
    dict(
        prompt_key="narrative_summary",
        prompt_version="v4",
        task_type="narrative_summary",
        prompt_text=NARRATIVE_SUMMARY_PROMPT,
        model_name=None,
        # num_predict: Ollama's default output-token cap is too small for a
        # multi-paragraph narrative and was silently truncating the response
        # mid-string -- confirmed live 2026-09-01 (json.JSONDecodeError at a
        # suspiciously consistent line/column across different content was
        # the tell: every failure was a response cut off before its closing
        # quote/brace, not genuinely malformed JSON).
        model_params={"temperature": 0.2, "num_predict": 800},
        json_schema={"title": "str", "narrative_markdown": "str"},
        active=True,
    ),
]
