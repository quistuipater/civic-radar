"""Coordinates Ollama (primary) and Claude (fallback-only escalation) --
see CLAUDE.md's "local-first... cloud AI is an optional manual escalation
path only, never a default dependency" principle. Every structured-
extraction call site in this codebase should go through generate_json()
here instead of calling ollama_client.generate_json directly, so the
escalation policy lives in one place rather than being reimplemented at
each call site.

Escalates to Claude ONLY on a hard Ollama failure (HTTP error or
unparseable JSON) -- never merely because the model returned a valid but
empty/small result. A prompt correctly returning {"assertions": []} (or
similarly empty output for another task) is often the right answer, not a
failure, and treating it as one would turn "nothing found" into wasted
cloud spend and, worse, a second guess that could contradict the first
one for no real reason.
"""

import logging

from app.ai import claude_client, ollama_client

logger = logging.getLogger(__name__)


def generate_json(
    ollama_model: str, prompt: str, timeout: float = 120.0, options: dict | None = None
) -> tuple[dict | None, str | None]:
    output_json, error = ollama_client.generate_json(ollama_model, prompt, timeout=timeout, options=options)
    if error is None:
        return output_json, None
    if not claude_client.is_available():
        return output_json, error
    logger.warning("ollama call failed (%s); escalating to Claude fallback", error)
    return claude_client.generate_json(prompt, timeout=timeout, options=options)
