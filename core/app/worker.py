"""Scheduler loop: polls due sources, then works through the parse -> classify ->
match -> alert backlog. Runs as its own container (prd.md recommends n8n for
scheduling; this Python loop is the Phase-0 stand-in — swap in n8n later without
changing anything downstream, since it only calls ingest_source() per tick).
"""

import logging
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import exists

from app.ai.pipeline import CLASSIFIABLE_TYPES, run_ai_pipeline
from app.alerting import create_alert_from_classification
from app.config import settings
from app.db import SessionLocal
from app.ingestion.crime_data import ingest_crime_source
from app.ingestion.legistar import ingest_legistar
from app.ingestion.meeting_audio import ingest_meeting_audio
from app.ingestion.onbase_agenda import ingest_onbase_agenda
from app.ingestion.pipeline import ingest_source
from app.ingestion.scc_planning_search import ingest_scc_planning_search
from app.issue_matching import match_document_to_issue
from app.log_handler import DbLogHandler, prune_app_logs
from app.models import AiOutput, Document, Source
from app.parsing.service import parse_document

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

BATCH_SIZE = 25

_last_prune_at: datetime | None = None
PRUNE_INTERVAL = timedelta(days=1)


def maybe_prune_app_logs() -> None:
    global _last_prune_at
    now = datetime.now(timezone.utc)
    if _last_prune_at is not None and now - _last_prune_at < PRUNE_INTERVAL:
        return
    db = SessionLocal()
    try:
        prune_app_logs(db)
    finally:
        db.close()
    _last_prune_at = now


def _bespoke_ingestors() -> dict:
    """Non-generic ingestion: sources whose fetch_method needs bespoke,
    session-stateful logic instead of the generic ingest_source() dispatch
    (see each ingestor's module docstring). Registering a new bespoke
    connector here is the only worker.py change a new city ever needs -- no
    more per-city elif branches.

    Built fresh on each call (cheap -- called once per tick, not per
    source) rather than as a module-level constant, so it re-reads whatever
    is currently bound to each name in this module's namespace -- same as
    the plain elif-chain this replaced, and needed so tests can
    monkeypatch e.g. worker.ingest_crime_source and have dispatch honor it.
    """
    return {
        "arcgis_feature_query": ingest_crime_source,
        "granicus_podcast_rss": ingest_meeting_audio,
        "onbase_agenda_online": ingest_onbase_agenda,
        "scc_planning_search": ingest_scc_planning_search,
        "legistar_api": ingest_legistar,
    }


def is_due(source: Source, now: datetime) -> bool:
    if not source.last_fetched_at:
        return True
    interval = timedelta(minutes=source.polling_interval_minutes or 240)
    return now - source.last_fetched_at >= interval


def run_ingestion_tick() -> None:
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        sources = db.query(Source).filter(Source.enabled.is_(True)).all()
        for source in sources:
            if not is_due(source, now):
                continue
            try:
                ingestor = _bespoke_ingestors().get(source.fetch_method, ingest_source)
                ingestor(db, source)
            except Exception:
                db.rollback()
                logger.exception("ingestion crashed for source %s", source.name, extra={"source_id": source.id})
    finally:
        db.close()


def run_parsing_batch() -> None:
    db = SessionLocal()
    try:
        pending = (
            db.query(Document).filter(Document.parser_status == "pending").limit(BATCH_SIZE).all()
        )
        for document in pending:
            try:
                parse_document(db, document)
            except Exception:
                db.rollback()
                logger.exception("parsing crashed for document %s", document.id, extra={"source_id": document.source_id})
    finally:
        db.close()


def run_ai_batch() -> None:
    db = SessionLocal()
    try:
        already_classified = exists().where(
            (AiOutput.input_ref_type == "document")
            & (AiOutput.input_ref_id == Document.id)
            & (AiOutput.task_type == "classification")
        )
        unclassified = (
            db.query(Document)
            .filter(
                Document.parser_status == "parsed",
                Document.document_type.in_(CLASSIFIABLE_TYPES),
                ~already_classified,
            )
            .limit(BATCH_SIZE)
            .all()
        )
        for document in unclassified:
            try:
                run_ai_pipeline(db, document)
                issue = match_document_to_issue(db, document)
                latest = (
                    db.query(AiOutput)
                    .filter(
                        AiOutput.input_ref_type == "document",
                        AiOutput.input_ref_id == document.id,
                        AiOutput.task_type == "classification",
                    )
                    .order_by(AiOutput.created_at.desc())
                    .first()
                )
                if latest and latest.output_json:
                    create_alert_from_classification(db, document, latest, issue)
            except Exception:
                db.rollback()
                logger.exception("AI pipeline crashed for document %s", document.id, extra={"source_id": document.source_id})
    finally:
        db.close()


def tick() -> None:
    run_ingestion_tick()
    run_parsing_batch()
    run_ai_batch()
    maybe_prune_app_logs()


def main() -> None:
    handler = DbLogHandler(SessionLocal)
    handler.setLevel(logging.ERROR)
    logging.getLogger().addHandler(handler)
    logger.info("%s worker starting (tick every %ss)", settings.project_name, settings.worker_tick_seconds)
    while True:
        try:
            tick()
        except Exception:
            logger.exception("worker tick failed")
        time.sleep(settings.worker_tick_seconds)


if __name__ == "__main__":
    main()
