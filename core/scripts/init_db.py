"""Create the pgvector extension and all tables. Safe to re-run."""

from sqlalchemy import text

from app import models  # noqa: F401  (registers models on Base.metadata)
from app.db import Base, engine
from app.organization_tracker import models as org_tracker_models  # noqa: F401


def main() -> None:
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.create_all(bind=engine)
    print("Database schema ready.")


if __name__ == "__main__":
    main()
