"""Tests for the WhisperX HTTP client -- same degradation contract as
ollama_client.py (prd.md 21: an unreachable model server must never take
down ingestion). httpx.Client is mocked so these run against controlled
failure modes rather than whatever WHISPERX_BASE_URL happens to resolve to.
"""

import httpx

import app.ai.whisperx_client as whisperx_client_module
from app.ai.whisperx_client import is_available, transcribe


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

    def post(self, url, files):
        if self._raise_error:
            raise self._raise_error
        return self._response

    def get(self, url):
        if self._raise_error:
            raise self._raise_error
        return self._response


def install_fake_client(monkeypatch, response=None, raise_error=None):
    monkeypatch.setattr(
        whisperx_client_module.httpx, "Client", lambda **kwargs: FakeClient(response=response, raise_error=raise_error)
    )


class TestTranscribe:
    def test_returns_parsed_result_on_success(self, monkeypatch, tmp_path):
        audio_path = tmp_path / "audio.mp3"
        audio_path.write_bytes(b"fake audio bytes")
        response = FakeResponse(
            json_data={"language": "en", "segments": [{"start": 0.0, "end": 1.0, "text": "hello", "speaker": "SPEAKER_00"}]}
        )
        install_fake_client(monkeypatch, response=response)

        result, error = transcribe(str(audio_path))

        assert result == {"language": "en", "segments": [{"start": 0.0, "end": 1.0, "text": "hello", "speaker": "SPEAKER_00"}]}
        assert error is None

    def test_returns_error_on_http_failure(self, monkeypatch, tmp_path):
        audio_path = tmp_path / "audio.mp3"
        audio_path.write_bytes(b"fake audio bytes")
        install_fake_client(monkeypatch, raise_error=httpx.ConnectError("connection refused"))

        result, error = transcribe(str(audio_path))

        assert result is None
        assert "whisperx request failed" in error

    def test_returns_error_on_non_2xx_status(self, monkeypatch, tmp_path):
        audio_path = tmp_path / "audio.mp3"
        audio_path.write_bytes(b"fake audio bytes")
        response = FakeResponse(status_code=500, raise_error=httpx.HTTPStatusError("error", request=None, response=None))
        install_fake_client(monkeypatch, response=response)

        result, error = transcribe(str(audio_path))

        assert result is None
        assert "whisperx request failed" in error

    def test_returns_error_when_audio_file_is_missing(self, monkeypatch, tmp_path):
        missing_path = tmp_path / "does_not_exist.mp3"

        result, error = transcribe(str(missing_path))

        assert result is None
        assert "could not read audio file" in error


class TestIsAvailable:
    def test_returns_true_when_models_loaded(self, monkeypatch):
        install_fake_client(monkeypatch, response=FakeResponse(status_code=200, json_data={"models_loaded": True}))
        assert is_available() is True

    def test_returns_false_when_models_not_yet_loaded(self, monkeypatch):
        install_fake_client(monkeypatch, response=FakeResponse(status_code=200, json_data={"models_loaded": False}))
        assert is_available() is False

    def test_returns_false_on_non_200_response(self, monkeypatch):
        install_fake_client(monkeypatch, response=FakeResponse(status_code=503, json_data={}))
        assert is_available() is False

    def test_returns_false_on_connection_error(self, monkeypatch):
        install_fake_client(monkeypatch, raise_error=httpx.ConnectError("connection refused"))
        assert is_available() is False
