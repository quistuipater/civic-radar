"""Per-city structured data that doesn't fit a scalar Settings/env-var field.

Scalar per-city values (project_name, database_url, model pins, etc.) go
through Settings (app/config.py) via each city's docker-compose.yml
environment section. Structured data -- right now just crime_data.py's
per-agency ArcGIS field-mapping config -- can't be expressed as a single env
var without an awkward JSON blob, so it lives here instead.

This file is the default/fallback (no crime-data source configured). Cities
that have one (Ventura, Boston) bind-mount their own
cities/<city>/city_settings.py over this path in their docker-compose.yml,
the same way ./backend:/app already bind-mounts the whole app tree.
"""

CRIME_AGENCY_CONFIG: dict = {}
