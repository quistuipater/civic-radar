"""Ventura's override for app/city_config.py — bind-mounted over that path in
cities/ventura/docker-compose.yml. See app/city_config.py's docstring for why
this exists as a separate file rather than a Settings/env-var field.
"""

CRIME_AGENCY_CONFIG = {
    "Ventura Police Department": {
        "external_id_field": "GlobalID",
        # created_date looked like a per-record cursor (esriFieldTypeDate,
        # varies per esri docs) but turned out not to be usable as one --
        # verified live 2026-07-08: every single one of the 84,327 rows
        # shares the *exact same* created_date value (a bulk-load artifact,
        # not "when this row was added"), AND the field silently fails to
        # filter via `where` at all (a `created_date > TIMESTAMP '...'`
        # query returns the full unfiltered count regardless of the
        # threshold, while the same query against Incident_Date_Start
        # filters correctly) -- so incremental sync via this field is
        # unreliable twice over. Falls back to full re-fetch + dedupe by
        # GlobalID every poll, same as VC Sheriff.
        "created_date_field": None,
        "incident_date_field": "Incident_Date_Start",
        "incident_date_end_field": "Incident_Date_End",
        "field_map": {
            "report_number": "Report_Number",
            "offense_category": "Offense_Category",
            "offense_type": "Offense_Type",
            "generalized_address": "GeneralizedAddress",
            "council_district": "Council_District",
            "beat": "Beat",
            "community_council": "Community_Council",
        },
    },
    "Ventura County Sheriff's Office": {
        "external_id_field": "FID",
        "created_date_field": None,
        "incident_date_field": None,
        "incident_date_end_field": None,
        "field_map": {
            "report_number": "Report_Number",
            "offense_category": "Crime_Category",
            "offense_type": "Public_Category",
            "beat": "Beat",
        },
    },
}

# No CKAN-datastore permit/inspection feed has been identified for Ventura
# (unlike Boston's data.boston.gov sources) -- empty, matching
# app/city_config.py's own default, so app.ingestion.building_permits/
# food_inspections's unconditional import in worker.py still resolves.
BUILDING_PERMITS_CONFIG: dict = {}
FOOD_INSPECTIONS_CONFIG: dict = {}
