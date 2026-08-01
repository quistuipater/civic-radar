"""Tests for the unified /api/logs endpoint: merges Fetch (pipeline),
AppLog (error), and AiOutput (inference) rows into one timestamp-sorted
feed, with type/source filtering and after/before cursor pagination.
"""

from datetime import timedelta

from app.models import Fetch

from .conftest import make_ai_output, make_app_log, make_document, make_source, utcnow


class TestListLogsByType:
    def test_pipeline_entries_include_source_name_and_status(self, client, db):
        source = make_source(db, name="Agenda Source")
        db.add(Fetch(source_id=source.id, status="ok", http_status=200, items_found=5))
        db.commit()

        resp = client.get("/api/logs?type=pipeline")

        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 1
        assert body[0]["type"] == "pipeline"
        assert body[0]["source_name"] == "Agenda Source"
        assert body[0]["level"] == "ok"
        assert "Agenda Source: ok" in body[0]["summary"]
        assert "5 items" in body[0]["summary"]

    def test_error_entries_carry_message_and_traceback(self, client, db):
        make_app_log(db, message="worker tick failed", traceback="Traceback...\nRuntimeError: boom")
        db.commit()

        resp = client.get("/api/logs?type=error")

        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 1
        assert body[0]["type"] == "error"
        assert body[0]["summary"] == "worker tick failed"
        assert body[0]["detail"] == "Traceback...\nRuntimeError: boom"

    def test_inference_entries_include_task_and_model_in_summary(self, client, db):
        source = make_source(db, name="Inference Source")
        document = make_document(db, source=source)
        make_ai_output(db, document.id, task_type="classification", model_name="qwen3:8b")
        db.commit()

        resp = client.get("/api/logs?type=inference")

        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 1
        assert body[0]["type"] == "inference"
        assert body[0]["level"] == "ok"
        assert body[0]["summary"] == "classification via qwen3:8b"
        assert body[0]["source_name"] == "Inference Source"

    def test_inference_entry_with_error_message_has_error_level(self, client, db):
        document = make_document(db)
        make_ai_output(db, document.id, error_message="ollama unreachable")
        db.commit()

        resp = client.get("/api/logs?type=inference")

        body = resp.json()
        assert body[0]["level"] == "error"
        assert body[0]["detail"] == "ollama unreachable"

    def test_all_type_merges_and_sorts_newest_first(self, client, db):
        source = make_source(db)
        now = utcnow()
        db.add(Fetch(source_id=source.id, status="ok", fetched_at=now - timedelta(minutes=2)))
        make_app_log(db, message="most recent", created_at=now)
        document = make_document(db, source=source)
        make_ai_output(db, document.id, created_at=now - timedelta(minutes=1))
        db.commit()

        resp = client.get("/api/logs?type=all")

        body = resp.json()
        assert [e["type"] for e in body] == ["error", "inference", "pipeline"]


class TestListLogsBySource:
    def test_strict_source_filter_for_pipeline(self, client, db):
        matching = make_source(db, name="Matching")
        other = make_source(db, name="Other")
        db.add(Fetch(source_id=matching.id, status="ok"))
        db.add(Fetch(source_id=other.id, status="ok"))
        db.commit()

        resp = client.get(f"/api/logs?type=pipeline&source_id={matching.id}")

        body = resp.json()
        assert len(body) == 1
        assert body[0]["source_name"] == "Matching"

    def test_error_filter_includes_general_errors_with_no_source(self, client, db):
        matching = make_source(db, name="Matching")
        other = make_source(db, name="Other")
        make_app_log(db, message="scoped to matching", source_id=matching.id)
        make_app_log(db, message="scoped to other", source_id=other.id)
        make_app_log(db, message="general error", source_id=None)
        db.commit()

        resp = client.get(f"/api/logs?type=error&source_id={matching.id}")

        summaries = {e["summary"] for e in resp.json()}
        assert summaries == {"scoped to matching", "general error"}

    def test_all_sources_returns_everything(self, client, db):
        make_app_log(db, message="one", source_id=make_source(db).id)
        db.commit()

        resp = client.get("/api/logs?type=error&source_id=all")

        assert len(resp.json()) == 1


class TestListLogsPagination:
    def test_after_cursor_returns_only_newer_entries(self, client, db):
        now = utcnow()
        make_app_log(db, message="old", created_at=now - timedelta(minutes=10))
        make_app_log(db, message="new", created_at=now)
        db.commit()

        resp = client.get(
            "/api/logs", params={"type": "error", "after": (now - timedelta(minutes=5)).isoformat()}
        )

        summaries = [e["summary"] for e in resp.json()]
        assert summaries == ["new"]

    def test_before_cursor_returns_only_older_entries(self, client, db):
        now = utcnow()
        make_app_log(db, message="old", created_at=now - timedelta(minutes=10))
        make_app_log(db, message="new", created_at=now)
        db.commit()

        resp = client.get(
            "/api/logs", params={"type": "error", "before": (now - timedelta(minutes=5)).isoformat()}
        )

        summaries = [e["summary"] for e in resp.json()]
        assert summaries == ["old"]

    def test_limit_is_respected(self, client, db):
        for i in range(5):
            make_app_log(db, message=f"entry-{i}")
        db.commit()

        resp = client.get("/api/logs?type=error&limit=2")

        assert len(resp.json()) == 2
