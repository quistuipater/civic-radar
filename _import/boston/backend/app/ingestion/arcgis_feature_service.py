"""Fetcher for ArcGIS FeatureServer layers (open law-enforcement incident
data). Structurally different from the Document connectors: there's no page
to parse for links, just a paginated JSON query API. Verified live 2026-07-07
against Ventura PD's public crime-data FeatureServer -- no auth needed, but
the dataset (84k+ rows) is too large to re-fetch in full on every poll, so
callers should pass `since` (the max CrimeIncident.source_created_at already
ingested) to fetch only new records.

Esri's SQL dialect rejects a raw epoch-millis comparison against a date field
(verified live: `created_date > 1751000000000` -> 400 "Invalid query
parameters") -- date literals must use `TIMESTAMP 'YYYY-MM-DD HH:MM:SS'`.
"""

from datetime import datetime, timezone

import httpx

PAGE_SIZE = 2000


def fetch_new_features(
    feature_server_url: str,
    since_epoch_ms: int | None,
    created_date_field: str | None = "created_date",
    timeout: float = 30.0,
) -> list[dict]:
    """Returns raw ArcGIS feature attribute dicts, oldest first, filtered to
    created_date_field > since_epoch_ms if both are given. Paginates until
    exhausted. created_date_field must be None for layers with no such field
    (e.g. VC Sheriff's NIBRS layer) -- passing a field name that doesn't
    exist on the layer is a 400 from Esri, both in `where` and `orderByFields`.
    """
    if since_epoch_ms is not None and created_date_field:
        since_str = datetime.fromtimestamp(since_epoch_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        where = f"{created_date_field} > TIMESTAMP '{since_str}'"
    else:
        where = "1=1"
    params = {
        "where": where,
        "outFields": "*",
        "resultRecordCount": PAGE_SIZE,
        "f": "json",
    }
    if created_date_field:
        params["orderByFields"] = f"{created_date_field} ASC"

    features: list[dict] = []
    offset = 0
    with httpx.Client(timeout=timeout) as client:
        while True:
            resp = client.get(
                f"{feature_server_url}/query",
                params={**params, "resultOffset": offset},
            )
            resp.raise_for_status()
            data = resp.json()
            if "error" in data:
                raise RuntimeError(f"ArcGIS query error: {data['error']}")
            batch = [f["attributes"] for f in data.get("features", [])]
            features.extend(batch)
            if len(batch) < PAGE_SIZE:
                break
            offset += PAGE_SIZE
    return features
