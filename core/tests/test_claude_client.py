"""Tests for the Anthropic HTTP client -- mirrors test_ollama_client.py's
pattern of mocking httpx.Client so these run against controlled failure
modes rather than a real API key/network call.
"""

import httpx

import app.ai.claude_client as claude_client_module
from app.ai.claude_client import generate_json, is_available


class FakeResponse:
    def __init__(self, json_data=None, raise_error=None):
        self._json_data = json_data
        self._raise_error = raise_error

    def raise_for_status(self):
        if self._raise_error:
            raise self._raise_error

    def json(self):
        return self._json_data


class FakeClient:
    def __init__(self, response=None, raise_error=None):
        self._response = response
        self._raise_error = raise_error

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def post(self, url, headers, json):
        if self._raise_error:
            raise self._raise_error
        return self._response


def install_fake_client(monkeypatch, response=None, raise_error=None):
    monkeypatch.setattr(
        claude_client_module.httpx, "Client", lambda **kwargs: FakeClient(response=response, raise_error=raise_error)
    )


def install_api_key(monkeypatch, key="test-key"):
    monkeypatch.setattr(claude_client_module.settings, "anthropic_api_key", key)


class TestIsAvailable:
    def test_false_when_no_api_key_configured(self, monkeypatch):
        monkeypatch.setattr(claude_client_module.settings, "anthropic_api_key", None)
        assert is_available() is False

    def test_true_when_api_key_configured(self, monkeypatch):
        install_api_key(monkeypatch)
        assert is_available() is True


class TestGenerateJson:
    def test_returns_error_when_no_api_key_configured(self, monkeypatch):
        monkeypatch.setattr(claude_client_module.settings, "anthropic_api_key", None)

        result, error = generate_json("some prompt")

        assert result is None
        assert "ANTHROPIC_API_KEY" in error

    def test_returns_parsed_json_on_success(self, monkeypatch):
        install_api_key(monkeypatch)
        response = FakeResponse(json_data={"content": [{"type": "text", "text": '{"assertions": []}'}]})
        install_fake_client(monkeypatch, response=response)

        result, error = generate_json("some prompt")

        assert result == {"assertions": []}
        assert error is None

    def test_strips_markdown_code_fence(self, monkeypatch):
        install_api_key(monkeypatch)
        response = FakeResponse(
            json_data={"content": [{"type": "text", "text": '```json\n{"assertions": []}\n```'}]}
        )
        install_fake_client(monkeypatch, response=response)

        result, error = generate_json("some prompt")

        assert result == {"assertions": []}
        assert error is None

    def test_returns_error_on_http_failure(self, monkeypatch):
        install_api_key(monkeypatch)
        install_fake_client(monkeypatch, raise_error=httpx.ConnectError("connection refused"))

        result, error = generate_json("some prompt")

        assert result is None
        assert "claude request failed" in error

    def test_returns_error_when_response_is_not_valid_json(self, monkeypatch):
        install_api_key(monkeypatch)
        response = FakeResponse(json_data={"content": [{"type": "text", "text": "not valid json"}]})
        install_fake_client(monkeypatch, response=response)

        result, error = generate_json("some prompt")

        assert result is None
        assert "invalid JSON" in error

    def test_forwards_temperature_option(self, monkeypatch):
        install_api_key(monkeypatch)
        seen_payloads = []

        class RecordingClient(FakeClient):
            def post(self, url, headers, json):
                seen_payloads.append(json)
                return self._response

        response = FakeResponse(json_data={"content": [{"type": "text", "text": "{}"}]})
        monkeypatch.setattr(
            claude_client_module.httpx, "Client", lambda **kwargs: RecordingClient(response=response)
        )

        generate_json("some prompt", options={"temperature": 0.1})

        assert seen_payloads[0]["temperature"] == 0.1
