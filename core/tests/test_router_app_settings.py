"""settings_store opens its own SessionLocal() (see test_settings_store.py's
module docstring), so these HTTP-level tests also monkeypatch
app.settings_store.SessionLocal to the test's isolated session factory --
otherwise the GET/POST calls below would silently read/write the real
database configured via DATABASE_URL instead of the per-test transaction.
"""

import app.settings_store as settings_store_module


class TestRemoteInferenceSettingEndpoint:
    def test_get_defaults_to_disabled(self, client, db_session_factory, monkeypatch):
        monkeypatch.setattr(settings_store_module, "SessionLocal", db_session_factory)

        resp = client.get("/api/settings/remote-inference")

        assert resp.status_code == 200
        assert resp.json() == {"enabled": False}

    def test_post_enables_and_get_reflects_it(self, client, db_session_factory, monkeypatch):
        monkeypatch.setattr(settings_store_module, "SessionLocal", db_session_factory)

        post_resp = client.post("/api/settings/remote-inference", json={"enabled": True})
        get_resp = client.get("/api/settings/remote-inference")

        assert post_resp.status_code == 200
        assert post_resp.json() == {"enabled": True}
        assert get_resp.json() == {"enabled": True}

    def test_post_can_disable_again(self, client, db_session_factory, monkeypatch):
        monkeypatch.setattr(settings_store_module, "SessionLocal", db_session_factory)

        client.post("/api/settings/remote-inference", json={"enabled": True})
        resp = client.post("/api/settings/remote-inference", json={"enabled": False})

        assert resp.json() == {"enabled": False}
