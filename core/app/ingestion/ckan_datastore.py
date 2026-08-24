"""Fetcher for Analyze Boston / data.boston.gov's CKAN datastore API.
Structurally the same family as arcgis_feature_service.py: no page to parse
for links, just a paginated query API returning structured rows. Uses
`datastore_search_sql` (confirmed enabled on data.boston.gov 2026-08-15)
rather than `datastore_search` so the cursor comparison (`cursor_field >
since`) happens server-side -- both Approved Building Permits and Food
Establishment Inspections are large enough (400k+ / 1M+ rows respectively)
that a client-side scan from row 0 on every poll isn't viable.

CKAN's SQL endpoint takes a resource id as the quoted "table name"; there is
no parameterized-query support, so `since` is interpolated directly. It is
always a `str()` of a datetime we produced ourselves (never external input),
so this does not take user-controlled data into the query.
"""

from datetime import datetime

import httpx

PAGE_SIZE = 5000


def fetch_new_records(
    api_base_url: str,
    resource_id: str,
    cursor_field: str,
    since: datetime | None,
    select_fields: list[str] | None = None,
    timeout: float = 60.0,
) -> list[dict]:
    """Returns raw datastore row dicts, oldest first, filtered to
    cursor_field > since if since is given. Paginates until exhausted.

    select_fields restricts the SQL SELECT list -- CKAN's `SELECT *`
    includes a server-generated `_full_text` tsvector column that, for
    these wide/high-row-count Boston datasets, made each 5000-row page
    ~6MB and ~16s (confirmed live 2026-08-15) even though nothing downstream
    uses it. Passing the caller's actual field list avoids that entirely.

    `ORDER BY cursor_field` alone is not a stable sort for OFFSET-based
    pagination when cursor_field has ties (confirmed live 2026-08-15: two
    Approved Building Permits rows shared the same issued_date second,
    landing on both sides of a page boundary and getting fetched twice,
    which the caller's dedup catches but a plain re-run would loop
    forever re-fetching that pair). `_id` (CKAN's own row identity column,
    always present) breaks ties deterministically.
    """
    select_clause = ", ".join(f'"{f}"' for f in select_fields) if select_fields else "*"
    where = f"WHERE \"{cursor_field}\" > '{since.isoformat()}'" if since else ""
    sql = (
        f'SELECT {select_clause} FROM "{resource_id}" {where} '
        f'ORDER BY "{cursor_field}" ASC, "_id" ASC LIMIT {PAGE_SIZE} OFFSET {{offset}}'
    )

    records: list[dict] = []
    offset = 0
    with httpx.Client(timeout=timeout) as client:
        while True:
            resp = client.get(f"{api_base_url}/api/3/action/datastore_search_sql", params={"sql": sql.format(offset=offset)})
            resp.raise_for_status()
            data = resp.json()
            if not data.get("success"):
                raise RuntimeError(f"CKAN datastore_search_sql error: {data.get('error')}")
            batch = data["result"]["records"]
            for row in batch:
                row.pop("_full_text", None)
            records.extend(batch)
            if len(batch) < PAGE_SIZE:
                break
            offset += PAGE_SIZE
    return records
