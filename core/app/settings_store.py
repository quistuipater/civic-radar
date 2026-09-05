"""Runtime-togglable operator settings backed by the app_settings table
(see AppSetting in app/models.py). Distinct from app/config.py's Settings,
which is env-var-backed and frozen at process start -- these are flags an
operator can flip from the dashboard without a restart.

Opens its own short-lived DB session per call rather than taking one as a
parameter, since the read happens deep inside ai_client.generate_json --
a hot path called from many places that don't otherwise need a db session.
"""

from app.db import SessionLocal
from app.models import AppSetting

REMOTE_INFERENCE_ENABLED_KEY = "remote_inference_enabled"


def get_remote_inference_enabled() -> bool:
    db = SessionLocal()
    try:
        row = db.get(AppSetting, REMOTE_INFERENCE_ENABLED_KEY)
        return row is not None and row.value == "true"
    finally:
        db.close()


def set_remote_inference_enabled(enabled: bool) -> None:
    db = SessionLocal()
    try:
        row = db.get(AppSetting, REMOTE_INFERENCE_ENABLED_KEY)
        value = "true" if enabled else "false"
        if row:
            row.value = value
        else:
            db.add(AppSetting(key=REMOTE_INFERENCE_ENABLED_KEY, value=value))
        db.commit()
    finally:
        db.close()
