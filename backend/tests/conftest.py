"""Shared test fixtures. Runs against a real Postgres+pgvector database (a
separate `civic_radar_test` DB on the same server as dev/prod) rather than
sqlite, since several models/queries depend on Postgres-only features
(pgvector's Vector column and cosine_distance, JSONB). Each test runs inside
a transaction that's rolled back afterward, so tests never see each other's
data and the schema only needs to be created once per test session.
"""

import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.db import Base, get_db
from app.main import app
from app.models import AiOutput, Document, Source

TEST_DATABASE_URL = settings.database_url.rsplit("/", 1)[0] + "/civic_radar_test"


@pytest.fixture(scope="session")
def test_engine():
    admin_engine = create_engine(settings.database_url, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname = 'civic_radar_test'")
        ).first()
        if not exists:
            conn.execute(text("CREATE DATABASE civic_radar_test"))
    admin_engine.dispose()

    engine = create_engine(TEST_DATABASE_URL, future=True)
    with engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.commit()
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def db(test_engine):
    # Application code under test calls db.commit()/db.rollback() for real
    # (ingest_source, ingest_crime_source, create_alert_from_classification,
    # ...). Binding a plain Session to an already-`.begin()`-started
    # Connection does NOT protect against that: session.commit() ends the
    # outer transaction for real, so a bare `transaction.rollback()` in
    # teardown silently becomes a no-op after the first commit (SQLAlchemy
    # emits "transaction already deassociated from connection") and rows
    # leak into civic_radar_test permanently instead of being isolated.
    # join_transaction_mode="create_savepoint" makes the session use a
    # SAVEPOINT for its own begin/commit/rollback cycle instead, restarting
    # a fresh savepoint after each inner commit, so the *outer* transaction
    # (and this fixture's rollback of it) stays intact regardless of how
    # many times the code under test calls commit().
    connection = test_engine.connect()
    transaction = connection.begin()
    session_factory = sessionmaker(
        bind=connection,
        autoflush=False,
        autocommit=False,
        future=True,
        join_transaction_mode="create_savepoint",
    )
    session = session_factory()
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def client(db):
    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def archive_root(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "archive_root", str(tmp_path))
    return tmp_path


def make_source(db, **overrides) -> Source:
    defaults = dict(
        name="Test Source",
        jurisdiction="City of Ventura",
        agency="Test Agency",
        body=None,
        source_type="agenda_center",
        authority_level="official_primary",
        url="https://example.invalid/source",
        fetch_method="html_pdf_harvest",
        connector="generic",
        polling_interval_minutes=240,
    )
    defaults.update(overrides)
    source = Source(**defaults)
    db.add(source)
    db.flush()
    return source


def make_document(db, source: Source | None = None, **overrides) -> Document:
    if source is None:
        source = make_source(db)
    defaults = dict(
        source_id=source.id,
        title="Test Document",
        document_type="agenda",
        archive_path="/archive/test/doc.pdf",
        content_hash=uuid.uuid4().hex,
        agency=source.agency,
        body=source.body,
    )
    defaults.update(overrides)
    document = Document(**defaults)
    db.add(document)
    db.flush()
    return document


def make_ai_output(db, input_ref_id, **overrides) -> AiOutput:
    defaults = dict(
        task_type="document_classification",
        model_name="test-model",
        prompt_version="v1",
        input_ref_type="document",
        input_ref_id=input_ref_id,
        output_json={},
        confidence="high",
    )
    defaults.update(overrides)
    output = AiOutput(**defaults)
    db.add(output)
    db.flush()
    return output


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
