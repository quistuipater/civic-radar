"""Tests for the Ollama HTTP client -- the thing every other AI-layer module
degrades through (prd.md 21 Reliability Requirements: a model-server outage
must never take down the pipeline). httpx.Client is mocked so these run
against controlled failure modes rather than whatever Ollama server
OLLAMA_BASE_URL happens to resolve to in a given environment.
"""

import httpx

import app.ai.ollama_client as ollama_client_module
from app.ai.ollama_client import embed, generate_json, is_available


class FakeResponse:
    def __init__(self, json_data=None, status_code=200, raise_error=None):
        self._json_data = json_data
        self.status_code = status_code
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

    def post(self, url, json):
        if self._raise_error:
            raise self._raise_error
        return self._response

    def get(self, url):
        if self._raise_error:
            raise self._raise_error
        return self._response


def install_fake_client(monkeypatch, response=None, raise_error=None):
    monkeypatch.setattr(
        ollama_client_module.httpx, "Client", lambda **kwargs: FakeClient(response=response, raise_error=raise_error)
    )


class TestGenerateJson:
    def test_returns_parsed_json_on_success(self, monkeypatch):
        response = FakeResponse(json_data={"response": '{"importance_score": 7}'})
        install_fake_client(monkeypatch, response=response)

        result, error = generate_json("test-model", "some prompt")

        assert result == {"importance_score": 7}
        assert error is None

    def test_returns_error_on_http_failure(self, monkeypatch):
        install_fake_client(monkeypatch, raise_error=httpx.ConnectError("connection refused"))

        result, error = generate_json("test-model", "some prompt")

        assert result is None
        assert "ollama request failed" in error

    def test_returns_error_on_non_2xx_status(self, monkeypatch):
        response = FakeResponse(status_code=500, raise_error=httpx.HTTPStatusError("error", request=None, response=None))
        install_fake_client(monkeypatch, response=response)

        result, error = generate_json("test-model", "some prompt")

        assert result is None
        assert "ollama request failed" in error

    def test_returns_error_when_model_response_is_not_valid_json(self, monkeypatch):
        response = FakeResponse(json_data={"response": "not valid json at all"})
        install_fake_client(monkeypatch, response=response)

        result, error = generate_json("test-model", "some prompt")

        assert result is None
        assert "invalid JSON" in error

    def test_missing_response_field_is_treated_as_empty_string(self, monkeypatch):
        response = FakeResponse(json_data={})
        install_fake_client(monkeypatch, response=response)

        result, error = generate_json("test-model", "some prompt")

        assert result is None
        assert "invalid JSON" in error


class TestEmbed:
    def test_returns_embedding_vector_on_success(self, monkeypatch):
        response = FakeResponse(json_data={"embedding": [0.1, 0.2, 0.3]})
        install_fake_client(monkeypatch, response=response)

        vector, error = embed("nomic-embed-text", "some text")

        assert vector == [0.1, 0.2, 0.3]
        assert error is None

    def test_returns_error_on_http_failure(self, monkeypatch):
        install_fake_client(monkeypatch, raise_error=httpx.ConnectError("connection refused"))

        vector, error = embed("nomic-embed-text", "some text")

        assert vector is None
        assert "ollama embedding request failed" in error


class TestIsAvailable:
    def test_returns_true_on_200_response(self, monkeypatch):
        install_fake_client(monkeypatch, response=FakeResponse(status_code=200))
        assert is_available() is True

    def test_returns_false_on_non_200_response(self, monkeypatch):
        install_fake_client(monkeypatch, response=FakeResponse(status_code=404))
        assert is_available() is False

    def test_returns_false_on_connection_error(self, monkeypatch):
        install_fake_client(monkeypatch, raise_error=httpx.ConnectError("connection refused"))
        assert is_available() is False
