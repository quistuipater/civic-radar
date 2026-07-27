"""Thin client for the WhisperX transcription service (whisperx_service/,
runs on madhatter -- see that directory's README). Same degradation
contract as ollama_client.py: on any failure, return None rather than
raising, so an unreachable/overloaded transcription service never takes
down ingestion for everything else.
"""

import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


def transcribe(audio_path: str, timeout: float = 3600.0) -> tuple[dict | None, str | None]:
    """Returns (result_or_None, error_message_or_None). result shape:
    {"language": "en", "segments": [{"start", "end", "text", "speaker"}, ...]}.
    Timeout defaults high -- a real meeting recording takes real minutes to
    process (~14x realtime observed on the RTX 5060 Ti), not the couple of
    seconds a typical Ollama call takes.
    """
    try:
        with open(audio_path, "rb") as f, httpx.Client(timeout=timeout) as client:
            resp = client.post(
                f"{settings.whisperx_base_url}/transcribe",
                files={"audio": (audio_path, f, "audio/mpeg")},
            )
            resp.raise_for_status()
            return resp.json(), None
    except httpx.HTTPError as exc:
        return None, f"whisperx request failed: {exc}"
    except OSError as exc:
        return None, f"could not read audio file: {exc}"


def is_available() -> bool:
    try:
        with httpx.Client(timeout=5.0) as client:
            resp = client.get(f"{settings.whisperx_base_url}/health")
            return resp.status_code == 200 and resp.json().get("models_loaded") is True
    except httpx.HTTPError:
        return False
