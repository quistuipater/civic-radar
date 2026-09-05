"""Tests for the Ollama/Claude routing coordinator. Ollama and Claude are
both monkeypatched directly (module-level functions) rather than through
HTTP mocking, since the behavior under test is the routing policy, not
either client's own request handling (that's covered by
test_ollama_client.py / test_claude_client.py).

get_remote_inference_enabled is monkeypatched in every test rather than
left to hit the real app_settings table via app.db.SessionLocal -- these
are meant to be fast, DB-free unit tests of the routing logic, and letting
the module-level flag check reach a real database would make them
integration tests by accident (and, worse, point at whatever
DATABASE_URL happens to be set in this environment).
"""

import app.ai.ai_client as ai_client_module
from app.ai.ai_client import generate_json


class TestGenerateJsonLocalFirst:
    """Default (remote inference toggle off) -- unchanged from the
    original Ollama-primary/Claude-fallback-only behavior.
    """

    def test_returns_ollama_result_directly_on_success(self, monkeypatch):
        monkeypatch.setattr(ai_client_module, "get_remote_inference_enabled", lambda: False)
        monkeypatch.setattr(ai_client_module.ollama_client, "generate_json", lambda *a, **k: ({"ok": True}, None))
        claude_called = []
        monkeypatch.setattr(
            ai_client_module.claude_client, "generate_json", lambda *a, **k: claude_called.append(1) or (None, None)
        )

        result, error = generate_json("some-model", "prompt")

        assert result == {"ok": True}
        assert error is None
        assert claude_called == []

    def test_does_not_escalate_when_ollama_returns_a_valid_empty_result(self, monkeypatch):
        # {"assertions": []} is often the CORRECT answer, not a failure --
        # escalating here would turn "nothing found" into wasted cloud
        # spend and a second, potentially contradictory guess.
        monkeypatch.setattr(ai_client_module, "get_remote_inference_enabled", lambda: False)
        monkeypatch.setattr(ai_client_module.ollama_client, "generate_json", lambda *a, **k: ({"assertions": []}, None))
        claude_called = []
        monkeypatch.setattr(
            ai_client_module.claude_client, "generate_json", lambda *a, **k: claude_called.append(1) or (None, None)
        )

        result, error = generate_json("some-model", "prompt")

        assert result == {"assertions": []}
        assert claude_called == []

    def test_escalates_to_claude_on_hard_ollama_failure_when_claude_is_available(self, monkeypatch):
        monkeypatch.setattr(ai_client_module, "get_remote_inference_enabled", lambda: False)
        monkeypatch.setattr(
            ai_client_module.ollama_client, "generate_json", lambda *a, **k: (None, "model returned invalid JSON")
        )
        monkeypatch.setattr(ai_client_module.claude_client, "is_available", lambda: True)
        monkeypatch.setattr(ai_client_module.claude_client, "generate_json", lambda *a, **k: ({"ok": "from claude"}, None))

        result, error = generate_json("some-model", "prompt")

        assert result == {"ok": "from claude"}
        assert error is None

    def test_returns_original_ollama_error_when_claude_is_not_available(self, monkeypatch):
        monkeypatch.setattr(ai_client_module, "get_remote_inference_enabled", lambda: False)
        monkeypatch.setattr(
            ai_client_module.ollama_client, "generate_json", lambda *a, **k: (None, "ollama request failed")
        )
        monkeypatch.setattr(ai_client_module.claude_client, "is_available", lambda: False)
        claude_called = []
        monkeypatch.setattr(
            ai_client_module.claude_client, "generate_json", lambda *a, **k: claude_called.append(1) or (None, None)
        )

        result, error = generate_json("some-model", "prompt")

        assert result is None
        assert error == "ollama request failed"
        assert claude_called == []

    def test_passes_options_through_to_both_clients(self, monkeypatch):
        seen = {}

        def fake_ollama(model, prompt, timeout=120.0, options=None):
            seen["ollama_options"] = options
            return None, "model returned invalid JSON"

        def fake_claude(prompt, timeout=120.0, options=None):
            seen["claude_options"] = options
            return {"ok": True}, None

        monkeypatch.setattr(ai_client_module, "get_remote_inference_enabled", lambda: False)
        monkeypatch.setattr(ai_client_module.ollama_client, "generate_json", fake_ollama)
        monkeypatch.setattr(ai_client_module.claude_client, "is_available", lambda: True)
        monkeypatch.setattr(ai_client_module.claude_client, "generate_json", fake_claude)

        generate_json("some-model", "prompt", options={"temperature": 0.1})

        assert seen["ollama_options"] == {"temperature": 0.1}
        assert seen["claude_options"] == {"temperature": 0.1}


class TestGenerateJsonRemoteFirst:
    """Remote inference toggle on -- Claude is tried first; a hard Claude
    failure falls back to local Ollama rather than surfacing an error.
    """

    def test_returns_claude_result_directly_on_success_without_calling_ollama(self, monkeypatch):
        monkeypatch.setattr(ai_client_module, "get_remote_inference_enabled", lambda: True)
        monkeypatch.setattr(ai_client_module.claude_client, "is_available", lambda: True)
        monkeypatch.setattr(ai_client_module.claude_client, "generate_json", lambda *a, **k: ({"ok": "from claude"}, None))
        ollama_called = []
        monkeypatch.setattr(
            ai_client_module.ollama_client, "generate_json", lambda *a, **k: ollama_called.append(1) or (None, None)
        )

        result, error = generate_json("some-model", "prompt")

        assert result == {"ok": "from claude"}
        assert error is None
        assert ollama_called == []

    def test_falls_back_to_ollama_on_hard_claude_failure(self, monkeypatch):
        monkeypatch.setattr(ai_client_module, "get_remote_inference_enabled", lambda: True)
        monkeypatch.setattr(ai_client_module.claude_client, "is_available", lambda: True)
        monkeypatch.setattr(ai_client_module.claude_client, "generate_json", lambda *a, **k: (None, "claude request failed"))
        monkeypatch.setattr(ai_client_module.ollama_client, "generate_json", lambda *a, **k: ({"ok": "from ollama"}, None))

        result, error = generate_json("some-model", "prompt")

        assert result == {"ok": "from ollama"}
        assert error is None

    def test_uses_ollama_directly_when_toggle_is_on_but_no_api_key_configured(self, monkeypatch):
        monkeypatch.setattr(ai_client_module, "get_remote_inference_enabled", lambda: True)
        monkeypatch.setattr(ai_client_module.claude_client, "is_available", lambda: False)
        monkeypatch.setattr(ai_client_module.ollama_client, "generate_json", lambda *a, **k: ({"ok": "from ollama"}, None))
        claude_called = []
        monkeypatch.setattr(
            ai_client_module.claude_client, "generate_json", lambda *a, **k: claude_called.append(1) or (None, None)
        )

        result, error = generate_json("some-model", "prompt")

        assert result == {"ok": "from ollama"}
        assert claude_called == []
