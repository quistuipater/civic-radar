"""Boston's override for app/city_config.py — bind-mounted over that path in
cities/boston/docker-compose.yml. See app/city_config.py's docstring for why
this exists as a separate file rather than a Settings/env-var field.
"""

CRIME_AGENCY_CONFIG = {
    "Boston Police Department": {
        "external_id_field": "OBJECTID",
        "created_date_field": "REPORT_DATE",
        "incident_date_field": "FROM_DATE",
        "incident_date_end_field": "TO_DATE",
        "field_map": {
            "report_number": "INC_NUM",
            "offense_category": "CRIME_CATEGORY",
            "offense_type": "OFFENSE_DESC",
            "generalized_address": "BLOCK",
            # Boston's schema has no council-district-equivalent field;
            # DISTRICT (BPD patrol district, e.g. "B2") is the closest
            # analog to "beat", and NEIGHBORHOOD is the closest analog to
            # "community_council" -- both are honest approximations, and
            # raw_attributes preserves the real field names/values either way.
            "beat": "DISTRICT",
            "community_council": "NEIGHBORHOOD",
        },
    },
}
