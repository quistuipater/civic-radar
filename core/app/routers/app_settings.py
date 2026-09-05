"""Runtime-togglable operator settings (see app/settings_store.py) --
distinct from app/config.py's env-var-backed Settings. Named app_settings
(not settings.py) to avoid shadowing app.config's module-level `settings`
object when both are imported in the same file.
"""

from fastapi import APIRouter
from pydantic import BaseModel

from app.settings_store import get_remote_inference_enabled, set_remote_inference_enabled

router = APIRouter(prefix="/api/settings", tags=["settings"])


class RemoteInferenceSetting(BaseModel):
    enabled: bool


@router.get("/remote-inference", response_model=RemoteInferenceSetting)
def get_remote_inference():
    return RemoteInferenceSetting(enabled=get_remote_inference_enabled())


@router.post("/remote-inference", response_model=RemoteInferenceSetting)
def update_remote_inference(body: RemoteInferenceSetting):
    set_remote_inference_enabled(body.enabled)
    return RemoteInferenceSetting(enabled=body.enabled)
