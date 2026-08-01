"""Process-wide error capture: DbLogHandler mirrors every ERROR+ log record
into the app_logs table, so operational errors show up in the dashboard's
Logs tab instead of only in Docker/stdout logs. Intended to be attached once,
to the root logger, in worker.py's main() and main.py's startup event (wiring
added in Task 2) -- once attached, any logger.error()/logger.exception() call
anywhere in the app is captured automatically, with no per-call-site changes
required.

prune_app_logs implements the 30-day retention policy for this table (to be
called via worker.py's maybe_prune_app_logs throttled call, added in Task 2).
"""

import logging
import sys
import traceback as traceback_module
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models import AppLog


class DbLogHandler(logging.Handler):
    def __init__(self, session_factory):
        super().__init__()
        self.session_factory = session_factory

    def emit(self, record: logging.LogRecord) -> None:
        # Must never raise: emit() is called synchronously from
        # logger.error()/.exception() call sites throughout the app, and a
        # handler exception here is NOT swallowed by the logging module --
        # it would propagate straight out of the very code path that's
        # already failing. A DB outage while logging an error must not
        # crash the caller.
        try:
            tb = None
            if record.exc_info:
                tb = "".join(traceback_module.format_exception(*record.exc_info))
            db = self.session_factory()
            try:
                db.add(
                    AppLog(
                        level=record.levelname,
                        logger_name=record.name,
                        message=record.getMessage(),
                        traceback=tb,
                        source_id=getattr(record, "source_id", None),
                    )
                )
                db.commit()
            finally:
                db.close()
        except Exception as exc:
            print(f"DbLogHandler failed to write log record: {exc}", file=sys.stderr)


def prune_app_logs(db: Session, cutoff: datetime | None = None) -> int:
    """Delete app_logs rows older than `cutoff` (default: 30 days ago).
    Returns the number of rows deleted."""
    if cutoff is None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    deleted = db.query(AppLog).filter(AppLog.created_at < cutoff).delete(synchronize_session=False)
    db.commit()
    return deleted
