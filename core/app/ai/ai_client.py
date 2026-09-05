"""Coordinates Ollama and Claude. Every structured-extraction call site in
this codebase should go through generate_json() here instead of calling
ollama_client.generate_json directly, so the routing policy lives in one
place rather than being reimplemented at each call site.

Two independent paths, both gated on settings_store's remote_inference_enabled
flag (an operator-flippable dashboard toggle -- see app/settings_store.py --
not the same thing as ANTHROPIC_API_KEY being configured):

- Toggle ON: Claude is tried first (2026-09-05 decision to make Claude the
  primary cloud provider); a hard Claude failure falls back to local Ollama
  rather than surfacing an error, so a transient API outage never blocks
  the pipeline.
- Toggle OFF (default): unchanged from the original local-first design --
  Ollama runs, and escalates to Claude ONLY on a hard Ollama failure (HTTP
  error or unparseable JSON), never merely because the model returned a
  valid but empty/small result. A prompt correctly returning
  {"assertions": []} (or similarly empty output for another task) is often
  the right answer, not a failure, and treating it as one would turn
  "nothing found" into wasted cloud spend and, worse, a second guess that
  could contradict the first one for no real reason.
"""

import logging

from app.ai import claude_client, ollama_client
from app.settings_store import get_remote_inference_enabled

logger = logging.getLogger(__name__)


def generate_json(
    ollama_model: str, prompt: str, timeout: float = 120.0, options: dict | None = None
) -> tuple[dict | None, str | None]:
    remote_first = get_remote_inference_enabled() and claude_client.is_available()

    if remote_first:
        output_json, error = claude_client.generate_json(prompt, timeout=timeout, options=options)
        if error is None:
            return output_json, None
        logger.warning("Claude call failed (%s); falling back to local Ollama", error)
        return ollama_client.generate_json(ollama_model, prompt, timeout=timeout, options=options)

    output_json, error = ollama_client.generate_json(ollama_model, prompt, timeout=timeout, options=options)
    if error is None:
        return output_json, None
    if not claude_client.is_available():
        return output_json, error
    logger.warning("ollama call failed (%s); escalating to Claude fallback", error)
    return claude_client.generate_json(prompt, timeout=timeout, options=options)
