"""Unified log feed: merges three existing signal sources into one
timestamp-sorted, filterable view --

- pipeline: Fetch rows (per-source ingestion attempts)
- error: AppLog rows (every ERROR+ log record process-wide, see log_handler.py)
- inference: AiOutput rows (per-document AI task runs)

Each sub-query independently applies the type/source/cursor filters and its
own `limit`, and results are merged and re-sorted before the final
truncation to `limit` -- this is deliberately more generous than a single
combined query would be, so a low-volume type (e.g. errors, hopefully) never
gets crowded out of an "all types" page by a high-volume one.
"""

import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import AiOutput, AppLog, Document, Fetch, Source
from app.schemas import LogEntryOut

router = APIRouter(prefix="/api/logs", tags=["logs"])


def _parse_source_id(raw: str | None) -> uuid.UUID | None:
    return None if raw in (None, "all") else uuid.UUID(raw)


def _pipeline_entries(
    db: Session,
    source_id: uuid.UUID | None,
    after: datetime | None,
    before: datetime | None,
    limit: int,
) -> list[LogEntryOut]:
    q = db.query(Fetch, Source.name).join(Source, Fetch.source_id == Source.id)
    if source_id is not None:
        q = q.filter(Fetch.source_id == source_id)
    if after is not None:
        q = q.filter(Fetch.fetched_at > after)
    if before is not None:
        q = q.filter(Fetch.fetched_at < before)
    q = q.order_by(Fetch.fetched_at.desc()).limit(limit)

    entries = []
    for fetch, source_name in q.all():
        summary = f"{source_name}: {fetch.status}"
        if fetch.http_status is not None:
            summary += f" (HTTP {fetch.http_status})"
        if fetch.items_found is not None:
            summary += f", {fetch.items_found} items"
        entries.append(
            LogEntryOut(
                id=str(fetch.id),
                type="pipeline",
                timestamp=fetch.fetched_at,
                level=fetch.status,
                source_id=str(fetch.source_id),
                source_name=source_name,
                summary=summary,
                detail=fetch.error_message or fetch.validation_message,
            )
        )
    return entries


def _error_entries(
    db: Session,
    source_id: uuid.UUID | None,
    after: datetime | None,
    before: datetime | None,
    limit: int,
) -> list[LogEntryOut]:
    q = db.query(AppLog, Source.name).outerjoin(Source, AppLog.source_id == Source.id)
    if source_id is not None:
        # Unlike pipeline/inference, error entries include unscoped
        # ("general") errors alongside ones tagged with this source --
        # see the design spec's source-picker section.
        q = q.filter(or_(AppLog.source_id == source_id, AppLog.source_id.is_(None)))
    if after is not None:
        q = q.filter(AppLog.created_at > after)
    if before is not None:
        q = q.filter(AppLog.created_at < before)
    q = q.order_by(AppLog.created_at.desc()).limit(limit)

    entries = []
    for app_log, source_name in q.all():
        entries.append(
            LogEntryOut(
                id=str(app_log.id),
                type="error",
                timestamp=app_log.created_at,
                level=app_log.level,
                source_id=str(app_log.source_id) if app_log.source_id else None,
                source_name=source_name,
                summary=app_log.message,
                detail=app_log.traceback,
            )
        )
    return entries


def _inference_entries(
    db: Session,
    source_id: uuid.UUID | None,
    after: datetime | None,
    before: datetime | None,
    limit: int,
) -> list[LogEntryOut]:
    q = (
        db.query(AiOutput, Source.id, Source.name)
        .outerjoin(
            Document,
            and_(AiOutput.input_ref_type == "document", AiOutput.input_ref_id == Document.id),
        )
        .outerjoin(Source, Document.source_id == Source.id)
    )
    if source_id is not None:
        q = q.filter(Source.id == source_id)
    if after is not None:
        q = q.filter(AiOutput.created_at > after)
    if before is not None:
        q = q.filter(AiOutput.created_at < before)
    q = q.order_by(AiOutput.created_at.desc()).limit(limit)

    entries = []
    for ai_output, src_id, src_name in q.all():
        entries.append(
            LogEntryOut(
                id=str(ai_output.id),
                type="inference",
                timestamp=ai_output.created_at,
                level="error" if ai_output.error_message else "ok",
                source_id=str(src_id) if src_id else None,
                source_name=src_name,
                summary=f"{ai_output.task_type} via {ai_output.model_name}",
                detail=ai_output.error_message,
            )
        )
    return entries


@router.get("", response_model=list[LogEntryOut])
def list_logs(
    type_: Literal["pipeline", "error", "inference", "all"] = Query("all", alias="type"),
    source_id: str | None = Query(default=None),
    after: str | None = Query(default=None),
    before: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
    db: Session = Depends(get_db),
) -> list[LogEntryOut]:
    parsed_source_id = _parse_source_id(source_id)
    parsed_after = datetime.fromisoformat(after) if after else None
    parsed_before = datetime.fromisoformat(before) if before else None

    entries: list[LogEntryOut] = []
    if type_ in ("pipeline", "all"):
        entries += _pipeline_entries(db, parsed_source_id, parsed_after, parsed_before, limit)
    if type_ in ("error", "all"):
        entries += _error_entries(db, parsed_source_id, parsed_after, parsed_before, limit)
    if type_ in ("inference", "all"):
        entries += _inference_entries(db, parsed_source_id, parsed_after, parsed_before, limit)

    entries.sort(key=lambda e: e.timestamp, reverse=True)
    return entries[:limit]
