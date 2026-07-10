"""Tests for the ArcGIS FeatureServer fetcher underlying crime-incident data
(currently ~109,500 rows across Ventura PD + VC Sheriff -- the largest
dataset in the system by row count). This module has already had two real
live bugs: Esri's SQL dialect rejecting a raw epoch-millis date comparison
(needed `TIMESTAMP 'YYYY-MM-DD HH:MM:SS'` literal syntax) and rejecting
`orderByFields`/`where` referencing a field a layer doesn't have. The
crime_data.py tests mock this module out entirely, so its actual
where-clause/pagination logic has never been exercised until now.
"""

import httpx
import pytest

import app.ingestion.arcgis_feature_service as arcgis_module
from app.ingestion.arcgis_feature_service import PAGE_SIZE, fetch_new_features


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("error", request=None, response=httpx.Response(self.status_code))

    def json(self):
        return self._payload


class FakeClient:
    """Stand-in for httpx.Client as used via `with httpx.Client(...) as client:`."""

    def __init__(self, get_fn):
        self._get_fn = get_fn
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get(self, url, params):
        self.calls.append({"url": url, "params": params})
        return self._get_fn(url, params)


def install_fake_client(monkeypatch, get_fn):
    fake = FakeClient(get_fn)
    monkeypatch.setattr(arcgis_module.httpx, "Client", lambda **kwargs: fake)
    return fake


def features_page(n, start_id=0):
    return {"features": [{"attributes": {"GlobalID": f"id-{start_id + i}"}} for i in range(n)]}


class TestWhereClauseConstruction:
    def test_no_cursor_and_default_field_uses_1_equals_1_but_still_orders(self, monkeypatch):
        client = install_fake_client(monkeypatch, lambda url, params: FakeResponse(features_page(0)))
        fetch_new_features("https://example.invalid/FeatureServer/0", None)
        params = client.calls[0]["params"]
        assert params["where"] == "1=1"
        assert params["orderByFields"] == "created_date ASC"

    def test_no_cursor_and_no_date_field_has_neither_where_condition_nor_order(self, monkeypatch):
        client = install_fake_client(monkeypatch, lambda url, params: FakeResponse(features_page(0)))
        fetch_new_features("https://example.invalid/FeatureServer/0", None, created_date_field=None)
        params = client.calls[0]["params"]
        assert params["where"] == "1=1"
        assert "orderByFields" not in params

    def test_cursor_with_date_field_builds_timestamp_literal(self, monkeypatch):
        client = install_fake_client(monkeypatch, lambda url, params: FakeResponse(features_page(0)))
        # 1751000000000 ms == 2025-06-27 04:53:20 UTC
        fetch_new_features("https://example.invalid/FeatureServer/0", 1751000000000, created_date_field="created_date")
        params = client.calls[0]["params"]
        assert params["where"] == "created_date > TIMESTAMP '2025-06-27 04:53:20'"
        assert params["orderByFields"] == "created_date ASC"

    def test_cursor_given_but_no_date_field_falls_back_to_full_refetch(self, monkeypatch):
        # This is the VC Sheriff case: a cursor might exist from an earlier
        # config but the layer has no created_date-equivalent field to
        # filter on, so it must fall back to "1=1" rather than sending a
        # `where` referencing a nonexistent field (a live 400 from Esri).
        client = install_fake_client(monkeypatch, lambda url, params: FakeResponse(features_page(0)))
        fetch_new_features("https://example.invalid/FeatureServer/0", 1751000000000, created_date_field=None)
        params = client.calls[0]["params"]
        assert params["where"] == "1=1"
        assert "orderByFields" not in params

    def test_custom_date_field_name_is_used_in_both_where_and_order(self, monkeypatch):
        client = install_fake_client(monkeypatch, lambda url, params: FakeResponse(features_page(0)))
        fetch_new_features("https://example.invalid/FeatureServer/0", 1751000000000, created_date_field="Incident_Date_Start")
        params = client.calls[0]["params"]
        assert "Incident_Date_Start > TIMESTAMP" in params["where"]
        assert params["orderByFields"] == "Incident_Date_Start ASC"


class TestPagination:
    def test_single_partial_page_stops_immediately(self, monkeypatch):
        client = install_fake_client(monkeypatch, lambda url, params: FakeResponse(features_page(5)))
        features = fetch_new_features("https://example.invalid/FeatureServer/0", None)
        assert len(features) == 5
        assert len(client.calls) == 1

    def test_full_page_triggers_a_second_request_with_advanced_offset(self, monkeypatch):
        pages = [features_page(PAGE_SIZE, start_id=0), features_page(3, start_id=PAGE_SIZE)]

        def get_fn(url, params):
            return FakeResponse(pages.pop(0))

        client = install_fake_client(monkeypatch, get_fn)
        features = fetch_new_features("https://example.invalid/FeatureServer/0", None)

        assert len(features) == PAGE_SIZE + 3
        assert len(client.calls) == 2
        assert client.calls[0]["params"]["resultOffset"] == 0
        assert client.calls[1]["params"]["resultOffset"] == PAGE_SIZE

    def test_zero_features_returns_empty_list_without_error(self, monkeypatch):
        install_fake_client(monkeypatch, lambda url, params: FakeResponse(features_page(0)))
        assert fetch_new_features("https://example.invalid/FeatureServer/0", None) == []

    def test_returns_raw_attribute_dicts_not_the_feature_wrapper(self, monkeypatch):
        install_fake_client(
            monkeypatch,
            lambda url, params: FakeResponse({"features": [{"attributes": {"GlobalID": "abc"}, "geometry": {}}]}),
        )
        features = fetch_new_features("https://example.invalid/FeatureServer/0", None)
        assert features == [{"GlobalID": "abc"}]


class TestErrorHandling:
    def test_esri_error_payload_raises_runtime_error_with_detail(self, monkeypatch):
        error_payload = {"error": {"code": 400, "message": "Invalid query parameters."}}
        install_fake_client(monkeypatch, lambda url, params: FakeResponse(error_payload))

        with pytest.raises(RuntimeError, match="Invalid query parameters"):
            fetch_new_features("https://example.invalid/FeatureServer/0", None)

    def test_http_error_status_propagates(self, monkeypatch):
        install_fake_client(monkeypatch, lambda url, params: FakeResponse({}, status_code=500))

        with pytest.raises(httpx.HTTPStatusError):
            fetch_new_features("https://example.invalid/FeatureServer/0", None)
