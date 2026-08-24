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

# CKAN datastore config for data.boston.gov (Analyze Boston), verified live
# 2026-08-15 via datastore_search_sql. Keyed by Source.agency.
BUILDING_PERMITS_CONFIG = {
    "Inspectional Services Department": {
        "api_base_url": "https://data.boston.gov",
        "resource_id": "6ddcd912-32a0-43df-9908-63574f8c7e77",
        "external_id_field": "_id",
        "cursor_field": "issued_date",
        "field_map": {
            "permit_type": "permittypedescr",
            "work_type": "worktype",
            "description": "description",
            "applicant": "applicant",
            "declared_valuation": "declared_valuation",
            "status": "status",
            "address": "address",
            "ward": "ward",
        },
        "issued_date_field": "issued_date",
        "expiration_date_field": "expiration_date",
    },
}

FOOD_INSPECTIONS_CONFIG = {
    "Boston Public Health Commission": {
        "api_base_url": "https://data.boston.gov",
        "resource_id": "4582bec6-2b4f-4f9e-bc55-cbaa73117f4c",
        "external_id_field": "_id",
        "cursor_field": "violdttm",
        "field_map": {
            "business_name": "businessname",
            "license_number": "licenseno",
            "result": "result",
            "violation_code": "violation",
            "violation_level": "viol_level",
            "violation_description": "violdesc",
            "violation_status": "viol_status",
            "comments": "comments",
            "address": "address",
        },
        "violation_date_field": "violdttm",
    },
}
