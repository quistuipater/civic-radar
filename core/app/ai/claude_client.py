"""Thin client for the Anthropic API. Used only as a fallback when Ollama
hard-fails (see ai_client.py) -- CLAUDE.md's "cloud AI is an optional
manual escalation path only, never a default dependency" principle. Same
degrade-on-failure contract as ollama_client: never raises, returns
(None, error_message) so a missing key or a bad response can't take down
the pipeline.
"""

import json
import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"


def is_available() -> bool:
    return bool(settings.anthropic_api_key)


def generate_json(prompt: str, timeout: float = 120.0, options: dict | None = None) -> tuple[dict | None, str | None]:
    """Returns (parsed_json_or_None, error_message_or_None). `options` mirrors
    ollama_client.generate_json's shape (e.g. {"temperature": 0.1}); only
    "temperature" is currently forwarded, since that's the only key any
    Prompt row in this codebase sets.
    """
    if not settings.anthropic_api_key:
        return None, "no ANTHROPIC_API_KEY configured"

    headers = {
        "x-api-key": settings.anthropic_api_key,
        "anthropic-version": ANTHROPIC_VERSION,
        "content-type": "application/json",
    }
    payload: dict = {
        "model": settings.claude_fallback_model,
        "max_tokens": 4096,
        "messages": [{"role": "user", "content": prompt}],
    }
    if options and "temperature" in options:
        payload["temperature"] = options["temperature"]

    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(ANTHROPIC_API_URL, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
            text = "".join(
                block.get("text", "") for block in data.get("content", []) if block.get("type") == "text"
            )
            return json.loads(_strip_code_fence(text)), None
    except httpx.HTTPError as exc:
        return None, f"claude request failed: {exc}"
    except (json.JSONDecodeError, ValueError) as exc:
        return None, f"claude returned invalid JSON: {exc}"


def _strip_code_fence(text: str) -> str:
    """Claude isn't given a strict JSON-mode flag the way Ollama's
    format="json" is -- it occasionally wraps output in a ```json fence
    even when the prompt asks for JSON only. Strip it defensively rather
    than let a cosmetic wrapper look like a parse failure.
    """
    text = text.strip()
    if not text.startswith("```"):
        return text
    lines = text.split("\n")
    if lines[-1].strip() == "```":
        lines = lines[1:-1]
    else:
        lines = lines[1:]
    return "\n".join(lines).strip()
