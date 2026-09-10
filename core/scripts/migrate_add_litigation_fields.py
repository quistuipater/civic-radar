"""One-off schema migration: add litigation-detail columns to `issues`.

This project has no migration tool (no Alembic) -- schema changes are
normally additive via Base.metadata.create_all (see init_db.py), which
handles *new* tables but does nothing for new columns on an already-existing
table in an already-deployed database. For that case, the established
pattern is a small one-off script like this one: raw `ALTER TABLE ... ADD
COLUMN IF NOT EXISTS`, safe to re-run, run manually once per deployed city.

Run after pulling this change, before restarting api/worker:
    docker compose run --rm api python scripts/migrate_add_litigation_fields.py
"""

from sqlalchemy import text

from app.db import engine

COLUMNS = [
    ("case_number", "TEXT"),
    ("court", "TEXT"),
    ("opposing_party", "TEXT"),
    ("city_role", "TEXT"),
    ("claim_type", "TEXT"),
    ("case_status", "TEXT"),
    ("cumulative_amount_authorized", "NUMERIC(12, 2)"),
]


def main() -> None:
    with engine.begin() as conn:
        for column_name, column_type in COLUMNS:
            conn.execute(text(f"ALTER TABLE issues ADD COLUMN IF NOT EXISTS {column_name} {column_type}"))
    print(f"Added/confirmed {len(COLUMNS)} litigation-detail column(s) on issues.")


if __name__ == "__main__":
    main()
