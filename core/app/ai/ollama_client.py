"""Thin client for a local Ollama server. Every call degrades gracefully:
on any failure we return None rather than raising, so a model-server outage
never takes down the ingestion pipeline (prd.md 21 Reliability Requirements).
"""

import json
import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


def generate_json(
    model: str, prompt: str, timeout: float = 120.0, options: dict | None = None
) -> tuple[dict | None, str | None]:
    """Returns (parsed_json_or_None, error_message_or_None). `options` is
    Ollama's per-request generation params (e.g. {"temperature": 0.1}) --
    pass a Prompt row's `model_params` here rather than leaving it unused
    metadata; every extraction task in this codebase stores a low
    temperature specifically to keep structured-JSON extraction consistent,
    and omitting it here means every call silently runs at Ollama's default
    temperature instead (confirmed live 2026-08-28: identical
    org_assertion_extraction prompt/text/model gave inconsistent
    assertion counts run-to-run before this was wired through).
    """
    payload: dict = {"model": model, "prompt": prompt, "format": "json", "stream": False}
    if options:
        payload["options"] = options
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(
                f"{settings.ollama_base_url}/api/generate",
                json=payload,
            )
            resp.raise_for_status()
            raw = resp.json().get("response", "")
            return json.loads(raw), None
    except httpx.HTTPError as exc:
        return None, f"ollama request failed: {exc}"
    except (json.JSONDecodeError, ValueError) as exc:
        return None, f"model returned invalid JSON: {exc}"


def generate_vision(model: str, prompt: str, image_b64: str, timeout: float = 120.0) -> tuple[str | None, str | None]:
    """Returns (transcribed_text_or_None, error_message_or_None). Same
    degrade-on-failure contract as generate_json -- a vision-model outage
    must not take down OCR, only fall back to whatever Tesseract already
    produced (see app/parsing/extract.py's _ocr_page).
    """
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(
                f"{settings.ollama_base_url}/api/generate",
                json={"model": model, "prompt": prompt, "images": [image_b64], "stream": False},
            )
            resp.raise_for_status()
            text = resp.json().get("response", "")
            return (text if text.strip() else None), None
    except httpx.HTTPError as exc:
        return None, f"ollama vision request failed: {exc}"


def embed(model: str, text: str, timeout: float = 60.0) -> tuple[list[float] | None, str | None]:
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(
                f"{settings.ollama_base_url}/api/embeddings",
                json={"model": model, "prompt": text},
            )
            resp.raise_for_status()
            return resp.json().get("embedding"), None
    except httpx.HTTPError as exc:
        return None, f"ollama embedding request failed: {exc}"


def is_available() -> bool:
    try:
        with httpx.Client(timeout=5.0) as client:
            resp = client.get(f"{settings.ollama_base_url}/api/tags")
            return resp.status_code == 200
    except httpx.HTTPError:
        return False
