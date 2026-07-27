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
from app.models import (
    AgendaItem,
    AiOutput,
    Alert,
    Document,
    Issue,
    ManualSubmission,
    Meeting,
    MeetingTranscript,
    Prompt,
    Source,
)

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
def db_connection(test_engine):
    connection = test_engine.connect()
    transaction = connection.begin()
    try:
        yield connection
    finally:
        transaction.rollback()
        connection.close()


@pytest.fixture
def db_session_factory(db_connection):
    # Application code under test calls db.commit()/db.rollback() for real
    # (ingest_source, ingest_crime_source, create_alert_from_classification,
    # worker.py's run_*() functions each doing SessionLocal(), ...). Binding a
    # plain Session to an already-`.begin()`-started Connection does NOT
    # protect against that: session.commit() ends the outer transaction for
    # real, so a bare `transaction.rollback()` in teardown silently becomes a
    # no-op after the first commit (SQLAlchemy emits "transaction already
    # deassociated from connection") and rows leak into civic_radar_test
    # permanently instead of being isolated. join_transaction_mode=
    # "create_savepoint" makes each session use a SAVEPOINT for its own
    # begin/commit/rollback cycle instead, restarting a fresh savepoint after
    # each inner commit, so the *outer* transaction (and this fixture's
    # rollback of it) stays intact regardless of how many times -- or how
    # many separate Session objects -- the code under test commits through.
    # Exposed as a factory (not just one `db` session) so worker.py tests can
    # monkeypatch SessionLocal to it: worker.py calls SessionLocal() fresh
    # per function rather than taking a `db` param, so it needs its own
    # sessions that still share this same isolated connection/transaction.
    return sessionmaker(
        bind=db_connection,
        autoflush=False,
        autocommit=False,
        future=True,
        join_transaction_mode="create_savepoint",
    )


@pytest.fixture
def db(db_session_factory):
    session = db_session_factory()
    try:
        yield session
    finally:
        session.close()


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
        jurisdiction="City of Santa Cruz",
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


def make_alert(db, document: Document | None = None, **overrides) -> Alert:
    if document is None and "issue_id" not in overrides:
        document = make_document(db)
    defaults = dict(
        document_id=document.id if document else None,
        alert_level=3,
        title="Test Alert",
        trigger_reason="test trigger",
        reviewed=False,
        status="new",
    )
    defaults.update(overrides)
    alert = Alert(**defaults)
    db.add(alert)
    db.flush()
    return alert


def make_issue(db, **overrides) -> Issue:
    defaults = dict(
        title="Test Issue",
        slug=f"test-issue-{uuid.uuid4().hex[:8]}",
        status="new",
    )
    defaults.update(overrides)
    issue = Issue(**defaults)
    db.add(issue)
    db.flush()
    return issue


def make_meeting(db, **overrides) -> Meeting:
    defaults = dict(
        jurisdiction="City of Santa Cruz",
        agency="City Clerk",
        body="City Council",
        start_time=utcnow(),
        status="scheduled",
    )
    defaults.update(overrides)
    meeting = Meeting(**defaults)
    db.add(meeting)
    db.flush()
    return meeting


def make_agenda_item(db, meeting: Meeting | None = None, **overrides) -> AgendaItem:
    if meeting is None:
        meeting = make_meeting(db)
    defaults = dict(
        meeting_id=meeting.id,
        title="Test Agenda Item",
    )
    defaults.update(overrides)
    item = AgendaItem(**defaults)
    db.add(item)
    db.flush()
    return item


def make_meeting_transcript(db, meeting: Meeting | None = None, source: Source | None = None, **overrides) -> MeetingTranscript:
    if source is None:
        source = make_source(db, fetch_method="granicus_podcast_rss")
    defaults = dict(
        meeting_id=meeting.id if meeting else None,
        source_id=source.id,
        title="Test Meeting Recording",
        archive_path="/archive/test/audio.mp3",
        content_hash=uuid.uuid4().hex,
        original_url="https://example.invalid/audio.mp3",
        duration_seconds=120.0,
        language="en",
        speaker_count=2,
        segments=[
            {"start": 0.0, "end": 5.0, "text": "Good evening.", "speaker": "SPEAKER_00"},
            {"start": 5.0, "end": 10.0, "text": "Motion carries.", "speaker": "SPEAKER_01"},
        ],
        model_name="whisperx-large-v3",
    )
    defaults.update(overrides)
    transcript = MeetingTranscript(**defaults)
    db.add(transcript)
    db.flush()
    return transcript


def make_manual_submission(db, **overrides) -> ManualSubmission:
    defaults = dict(
        submission_type="text",
        content_text="Someone said something on Nextdoor",
        claimed_source="Nextdoor",
    )
    defaults.update(overrides)
    submission = ManualSubmission(**defaults)
    db.add(submission)
    db.flush()
    return submission


def make_prompt(db, **overrides) -> Prompt:
    defaults = dict(
        prompt_key="test_prompt",
        prompt_version="v1",
        task_type="test_task",
        prompt_text="{text}",
        model_name="test-model",
        active=True,
    )
    defaults.update(overrides)
    prompt = Prompt(**defaults)
    db.add(prompt)
    db.flush()
    return prompt


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
