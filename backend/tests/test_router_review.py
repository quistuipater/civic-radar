from .conftest import make_alert, make_document, make_manual_submission, make_source


class TestReviewQueue:
    def test_only_surfaces_unreviewed_level_3_plus_alerts(self, db, client):
        make_alert(db, alert_level=4, reviewed=False, title="Should appear")
        make_alert(db, alert_level=2, reviewed=False, title="Too low a level")
        make_alert(db, alert_level=4, reviewed=True, title="Already reviewed")
        db.commit()

        resp = client.get("/api/review-queue")

        titles = [a["title"] for a in resp.json()["high_priority_alerts"]]
        assert titles == ["Should appear"]

    def test_surfaces_documents_with_parser_failures(self, db, client):
        make_document(db, parser_status="failed", parser_error="OCR timeout")
        make_document(db, parser_status="parsed")
        db.commit()

        resp = client.get("/api/review-queue")

        errors = resp.json()["extraction_errors"]
        assert len(errors) == 1
        assert errors[0]["parser_error"] == "OCR timeout"

    def test_surfaces_sources_with_3_plus_consecutive_failures(self, db, client):
        make_source(db, name="Flaky Source", consecutive_failures=5)
        make_source(db, name="Healthy Source", consecutive_failures=0)
        db.commit()

        resp = client.get("/api/review-queue")

        names = [s["name"] for s in resp.json()["source_failures"]]
        assert names == ["Flaky Source"]

    def test_surfaces_unresolved_manual_submissions(self, db, client):
        make_manual_submission(db, verification_status="unresolved", claimed_source="Nextdoor")
        make_manual_submission(db, verification_status="confirmed", claimed_source="Official notice")
        db.commit()

        resp = client.get("/api/review-queue")

        sources = [s["claimed_source"] for s in resp.json()["social_unverified"]]
        assert sources == ["Nextdoor"]

    def test_empty_database_returns_empty_sections_not_an_error(self, client):
        resp = client.get("/api/review-queue")
        assert resp.status_code == 200
        body = resp.json()
        assert body == {
            "high_priority_alerts": [],
            "extraction_errors": [],
            "source_failures": [],
            "social_unverified": [],
        }


class TestApproveAlert:
    def test_marks_alert_reviewed_and_approved(self, db, client):
        alert = make_alert(db, reviewed=False, status="new")
        db.commit()

        resp = client.post(f"/api/review/{alert.id}/approve", json={"note": "looks fine"})

        assert resp.status_code == 200
        body = resp.json()
        assert body["reviewed"] is True
        assert body["status"] == "approved"
        assert body["operator_note"] == "looks fine"

    def test_returns_404_for_unknown_id(self, client):
        resp = client.post("/api/review/00000000-0000-0000-0000-000000000000/approve", json={})
        assert resp.status_code == 404


class TestRejectAlert:
    def test_marks_alert_reviewed_and_rejected(self, db, client):
        alert = make_alert(db, reviewed=False, status="new")
        db.commit()

        resp = client.post(f"/api/review/{alert.id}/reject", json={"note": "false positive"})

        assert resp.status_code == 200
        body = resp.json()
        assert body["reviewed"] is True
        assert body["status"] == "rejected"
        assert body["operator_note"] == "false positive"

    def test_returns_404_for_unknown_id(self, client):
        resp = client.post("/api/review/00000000-0000-0000-0000-000000000000/reject", json={})
        assert resp.status_code == 404
