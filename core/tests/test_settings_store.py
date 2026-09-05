"""settings_store opens its own SessionLocal() rather than taking a `db`
parameter (same reason as worker.py -- see test_worker.py's module
docstring), so tests monkeypatch app.settings_store.SessionLocal to the
test's isolated session factory rather than letting it reach the real
database configured via DATABASE_URL.
"""

import app.settings_store as settings_store_module
from app.settings_store import get_remote_inference_enabled, set_remote_inference_enabled


class TestSettingsStore:
    def test_defaults_to_disabled_when_no_row_exists(self, monkeypatch, db_session_factory):
        monkeypatch.setattr(settings_store_module, "SessionLocal", db_session_factory)

        assert get_remote_inference_enabled() is False

    def test_set_then_get_round_trips_true(self, monkeypatch, db_session_factory):
        monkeypatch.setattr(settings_store_module, "SessionLocal", db_session_factory)

        set_remote_inference_enabled(True)

        assert get_remote_inference_enabled() is True

    def test_set_then_get_round_trips_false_after_true(self, monkeypatch, db_session_factory):
        monkeypatch.setattr(settings_store_module, "SessionLocal", db_session_factory)

        set_remote_inference_enabled(True)
        set_remote_inference_enabled(False)

        assert get_remote_inference_enabled() is False

    def test_set_updates_existing_row_rather_than_erroring_on_duplicate_key(self, monkeypatch, db_session_factory):
        monkeypatch.setattr(settings_store_module, "SessionLocal", db_session_factory)

        set_remote_inference_enabled(True)
        set_remote_inference_enabled(True)  # would violate a naive INSERT-only implementation

        assert get_remote_inference_enabled() is True
