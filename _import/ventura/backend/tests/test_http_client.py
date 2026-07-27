"""Tests for fetch_url -- the retry-decorated HTTP fetcher every connector
uses. httpx.Client is mocked; the retry-then-reraise test genuinely sleeps
a couple of real seconds (tenacity's wait_exponential(min=1, max=8) between
attempts) since faking out tenacity's own clock isn't worth the complexity
for one test.
"""

import httpx

import app.ingestion.http_client as http_client_module
from app.ingestion.http_client import fetch_url


class FakeResponse:
    def __init__(self, status_code=200):
        self.status_code = status_code
        self.headers = {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("error", request=None, response=self)


class FakeClient:
    def __init__(self, get_fn, seen_kwargs):
        self._get_fn = get_fn
        self._seen_kwargs = seen_kwargs

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get(self, url):
        return self._get_fn(url)


def install_fake_client(monkeypatch, get_fn):
    seen_kwargs = {}

    def fake_client_factory(**kwargs):
        seen_kwargs.update(kwargs)
        return FakeClient(get_fn, seen_kwargs)

    monkeypatch.setattr(http_client_module.httpx, "Client", fake_client_factory)
    return seen_kwargs


class TestFetchUrl:
    def test_returns_the_response_on_success(self, monkeypatch):
        install_fake_client(monkeypatch, lambda url: FakeResponse(200))

        response = fetch_url("https://example.invalid/page")

        assert response.status_code == 200

    def test_sends_the_configured_user_agent(self, monkeypatch):
        seen_kwargs = install_fake_client(monkeypatch, lambda url: FakeResponse(200))

        fetch_url("https://example.invalid/page")

        assert "User-Agent" in seen_kwargs["headers"]

    def test_follows_redirects(self, monkeypatch):
        seen_kwargs = install_fake_client(monkeypatch, lambda url: FakeResponse(200))

        fetch_url("https://example.invalid/page")

        assert seen_kwargs["follow_redirects"] is True

    def test_http_status_error_is_not_retried_and_propagates_immediately(self, monkeypatch):
        calls = []

        def fake_get(url):
            calls.append(1)
            return FakeResponse(404)

        install_fake_client(monkeypatch, fake_get)

        try:
            fetch_url("https://example.invalid/missing")
            assert False, "expected HTTPStatusError"
        except httpx.HTTPStatusError:
            pass

        assert len(calls) == 1  # not retried -- only TransportError/TimeoutException are

    def test_transport_error_is_retried_and_eventually_reraised(self, monkeypatch):
        calls = []

        def fake_get(url):
            calls.append(1)
            raise httpx.ConnectError("connection refused")

        install_fake_client(monkeypatch, fake_get)

        try:
            fetch_url("https://example.invalid/unreachable")
            assert False, "expected ConnectError to eventually propagate"
        except httpx.ConnectError:
            pass

        assert len(calls) == 3  # stop_after_attempt(3)
