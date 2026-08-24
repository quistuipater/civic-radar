"""Ingest inspection/violation line items from a CKAN-datastore-backed
open-data source (e.g. Analyze Boston's Food Establishment Inspections
dataset). Same shape as app/ingestion/crime_data.py. One row per violation
cited during an inspection -- the upstream feed has no separate
"violations" dataset, see FoodInspection's docstring in app/models.py.
"""

import logging
import time
import uuid

from dateutil import parser as date_parser
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.archive import archive_dir_for, now_utc, write_metadata
from app.city_config import FOOD_INSPECTIONS_CONFIG as AGENCY_CONFIG
from app.ingestion.ckan_datastore import fetch_new_records
from app.models import Fetch, FoodInspection, Source

logger = logging.getLogger(__name__)


def _parse_dt(value):
    if not value:
        return None
    try:
        return date_parser.isoparse(value)
    except (ValueError, TypeError):
        return None


def ingest_food_inspections(db: Session, source: Source) -> int:
    """Returns the number of new inspection/violation rows ingested."""
    started = time.monotonic()
    fetch = Fetch(source_id=source.id, status="pending")
    db.add(fetch)

    config = AGENCY_CONFIG.get(source.agency)
    if config is None:
        fetch.status = "error"
        fetch.validation_status = "error"
        fetch.validation_message = f"no FOOD_INSPECTIONS_CONFIG entry for agency {source.agency!r}"
        db.commit()
        logger.error("no FOOD_INSPECTIONS_CONFIG entry for %s; skipping", source.agency)
        return 0

    latest = (
        db.query(FoodInspection.violation_date)
        .filter(FoodInspection.source_id == source.id)
        .order_by(FoodInspection.violation_date.desc())
        .first()
    )
    since = latest[0] if latest and latest[0] else None

    select_fields = [
        config["external_id_field"],
        config["violation_date_field"],
        *config["field_map"].values(),
    ]
    try:
        records = fetch_new_records(
            config["api_base_url"], config["resource_id"], config["cursor_field"], since,
            select_fields=select_fields,
        )
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
        logger.warning("food inspections fetch failed for source %s: %s", source.name, exc)
        return 0

    fetch.status = "ok"
    fetch.items_found = len(records)
    fetch.validation_status = "ok" if since or records else "empty"

    if records:
        directory = archive_dir_for(source.jurisdiction, source.body, now_utc())
        write_metadata(
            directory,
            f"food_inspections_poll_{now_utc().strftime('%Y%m%dT%H%M%S')}.json",
            {"source_id": str(source.id), "count": len(records), "records": records},
        )

    # Bulk upsert (INSERT ... ON CONFLICT DO NOTHING) in chunks -- see
    # building_permits.py's identical comment. Same bottleneck and same
    # non-adjacent-duplicate pagination behavior confirmed live 2026-08-15,
    # at a larger dataset scale (1M+ rows) here.
    rows = []
    for attrs in records:
        raw_external_id = attrs.get(config["external_id_field"])
        if raw_external_id is None:
            continue
        rows.append(
            {
                "id": uuid.uuid4(),
                "source_id": source.id,
                "external_id": str(raw_external_id),
                "violation_date": _parse_dt(attrs.get(config["violation_date_field"])),
                "raw_attributes": attrs,
                **{field: attrs.get(source_field) for field, source_field in config["field_map"].items()},
            }
        )

    created = 0
    CHUNK = 2000
    for i in range(0, len(rows), CHUNK):
        chunk = rows[i : i + CHUNK]
        stmt = (
            pg_insert(FoodInspection)
            .values(chunk)
            .on_conflict_do_nothing(index_elements=["source_id", "external_id"])
        )
        result = db.execute(stmt)
        created += result.rowcount
        db.commit()

    fetch.duration_ms = int((time.monotonic() - started) * 1000)
    source.last_fetched_at = now_utc()
    source.consecutive_failures = 0
    source.last_error = None
    if created:
        source.last_changed_at = now_utc()
    db.commit()
    logger.info("ingested %d new food inspection/violation row(s) for %s", created, source.name)
    return created
