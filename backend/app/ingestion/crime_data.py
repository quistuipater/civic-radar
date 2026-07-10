"""Ingest incident records from an ArcGIS FeatureServer crime-data source.
A different shape from ingest_source()/Document: no PDF/HTML to archive then
parse, just structured rows synced incrementally where possible (prd.md
doesn't define this domain object -- see README "Potential future sources"
for how this differs from the Document-based pipeline). Each poll's raw
response is archived for archive-first, then rows are upserted into
crime_incidents.

Different agencies' FeatureServers can use meaningfully different schemas --
Ventura Civic Radar (this project's fork source) found one agency with a
stable GlobalID, a real incident-date field, and a created_date field usable
as an incremental-sync cursor, and a second agency with none of that (just
an integer Year, no address, FID instead of GlobalID as the unique id) --
AGENCY_CONFIG captures these per-agency differences; a source with no
`created_date_field` falls back to a full re-fetch every poll. Before
trusting any agency's `created_date`-shaped field as an incremental cursor,
verify it actually varies per row and actually filters via `where` -- one of
Ventura's two agencies had a field that looked like a per-record cursor but
silently failed both checks (every row shared one bulk-load timestamp, and
`where` filtering on it silently no-opped). No Boston agency has been added
below yet -- Boston Police Department publishes a well-known open "Crime
Incident Reports" dataset on Analyze Boston, but verify live whether it's
actually ArcGIS-FeatureServer-shaped (what this module and
arcgis_feature_service.py handle) or a different open-data platform
(Socrata/CKAN) before assuming this connector applies as-is -- see this
file's AGENCY_CONFIG and README's TODO section.
"""

import logging
import time
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.archive import archive_dir_for, now_utc, write_metadata
from app.ingestion.arcgis_feature_service import fetch_new_features
from app.models import CrimeIncident, Fetch, Source

logger = logging.getLogger(__name__)

# Keyed by Source.agency (exact string match). No Boston-area agency added
# yet -- verify whether Boston PD's "Crime Incident Reports" open dataset
# (published on Analyze Boston) is actually ArcGIS-FeatureServer-shaped
# before assuming this module applies; if so, add an entry here matching
# the pattern below. Example shape, generalized from Ventura Civic Radar's
# real entries (field names below are illustrative, not real -- inspect the
# actual FeatureServer's fields via its /query endpoint before filling this
# in):
#
# AGENCY_CONFIG = {
#     "Some Police Department": {
#         "external_id_field": "GlobalID",  # or whatever the layer's unique id field is
#         "created_date_field": None,  # only set this if it demonstrably varies per row
#                                       # AND filters correctly via `where` -- verify both
#                                       # before trusting it as an incremental cursor
#         "incident_date_field": "Incident_Date_Start",
#         "incident_date_end_field": "Incident_Date_End",
#         "field_map": {
#             "report_number": "Report_Number",
#             "offense_category": "Offense_Category",
#             "offense_type": "Offense_Type",
#             "generalized_address": "GeneralizedAddress",
#             "council_district": "Council_District",
#             "beat": "Beat",
#             "community_council": "Community_Council",
#         },
#     },
# }
AGENCY_CONFIG: dict = {}


def _epoch_ms_to_datetime(ms: int | None) -> datetime | None:
    if ms is None:
        return None
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)


def ingest_crime_source(db: Session, source: Source) -> int:
    """Returns the number of new incidents ingested."""
    started = time.monotonic()
    fetch = Fetch(source_id=source.id, status="pending")
    db.add(fetch)

    config = AGENCY_CONFIG.get(source.agency)
    if config is None:
        fetch.status = "error"
        fetch.validation_status = "error"
        fetch.validation_message = f"no AGENCY_CONFIG entry for agency {source.agency!r}"
        db.commit()
        logger.error("no AGENCY_CONFIG entry for %s; skipping", source.agency)
        return 0

    since_epoch_ms = None
    if config["created_date_field"]:
        latest = (
            db.query(CrimeIncident.source_created_at)
            .filter(CrimeIncident.source_id == source.id)
            .order_by(CrimeIncident.source_created_at.desc())
            .first()
        )
        since_epoch_ms = int(latest[0].timestamp() * 1000) if latest and latest[0] else None

    try:
        features = fetch_new_features(source.url, since_epoch_ms, created_date_field=config["created_date_field"])
    except Exception as exc:  # noqa: BLE001 - a bad poll must not crash the worker
        fetch.status = "error"
        fetch.error_message = str(exc)[:2000]
        fetch.validation_status = "error"
        fetch.validation_message = fetch.error_message
        fetch.duration_ms = int((time.monotonic() - started) * 1000)
        source.last_error = fetch.error_message
        source.consecutive_failures += 1
        source.last_fetched_at = now_utc()
        db.commit()
        logger.warning("crime data fetch failed for source %s: %s", source.name, exc)
        return 0

    fetch.status = "ok"
    fetch.items_found = len(features)
    if features:
        expected_fields = [config["external_id_field"], *config["field_map"].values()]
        missing_fields = [f for f in expected_fields if f not in features[0]]
        if missing_fields:
            fetch.validation_status = "schema_mismatch"
            fetch.validation_message = f"expected field(s) missing from response: {missing_fields}"
        else:
            fetch.validation_status = "ok"
    elif config["created_date_field"] is None:
        # This source can't sync incrementally, so it always re-fetches the
        # full dataset -- coming back empty is a real anomaly, not "nothing
        # new today" (see Ventura PD's incremental case below).
        fetch.validation_status = "empty"
        fetch.validation_message = "full-refresh source returned 0 features -- likely an upstream problem"
    else:
        # Incremental source (has a created_date_field): 0 new rows since
        # last poll is completely normal, not a red flag.
        fetch.validation_status = "ok"

    if features:
        directory = archive_dir_for(source.jurisdiction, source.body, now_utc())
        write_metadata(
            directory,
            f"crime_incidents_poll_{now_utc().strftime('%Y%m%dT%H%M%S')}.json",
            {"source_id": str(source.id), "count": len(features), "features": features},
        )

    created = 0
    for attrs in features:
        raw_external_id = attrs.get(config["external_id_field"])
        if raw_external_id is None:
            continue
        external_id = str(raw_external_id)
        existing = (
            db.query(CrimeIncident)
            .filter(CrimeIncident.source_id == source.id, CrimeIncident.external_id == external_id)
            .one_or_none()
        )
        if existing:
            continue
        incident_date_field = config["incident_date_field"]
        incident_date_end_field = config["incident_date_end_field"]
        created_date_field = config["created_date_field"]
        db.add(
            CrimeIncident(
                source_id=source.id,
                agency=source.agency,
                external_id=external_id,
                incident_date_start=_epoch_ms_to_datetime(attrs.get(incident_date_field)) if incident_date_field else None,
                incident_date_end=_epoch_ms_to_datetime(attrs.get(incident_date_end_field)) if incident_date_end_field else None,
                source_created_at=_epoch_ms_to_datetime(attrs.get(created_date_field)) if created_date_field else None,
                raw_attributes=attrs,
                **{field: attrs.get(source_field) for field, source_field in config["field_map"].items()},
            )
        )
        created += 1

    fetch.duration_ms = int((time.monotonic() - started) * 1000)
    source.last_fetched_at = now_utc()
    source.consecutive_failures = 0
    source.last_error = None
    if created:
        source.last_changed_at = now_utc()
    db.commit()
    logger.info("ingested %d new crime incident(s) for %s", created, source.name)
    return created
