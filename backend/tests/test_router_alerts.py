from .conftest import make_alert


class TestListAlerts:
    def test_filters_by_min_level(self, db, client):
        make_alert(db, alert_level=1, title="Low")
        make_alert(db, alert_level=4, title="High")
        db.commit()

        resp = client.get("/api/alerts", params={"min_level": 3})

        titles = [a["title"] for a in resp.json()]
        assert titles == ["High"]

    def test_filters_by_reviewed_status(self, db, client):
        make_alert(db, title="Reviewed", reviewed=True)
        make_alert(db, title="Unreviewed", reviewed=False)
        db.commit()

        resp = client.get("/api/alerts", params={"reviewed": "false"})

        titles = [a["title"] for a in resp.json()]
        assert titles == ["Unreviewed"]

    def test_limit_is_capped_at_500(self, db, client):
        make_alert(db)
        db.commit()

        resp = client.get("/api/alerts", params={"limit": 10000})

        assert resp.status_code == 200  # would 500 if the cap weren't applied and something downstream choked


class TestGetAlert:
    def test_returns_404_for_unknown_id(self, client):
        resp = client.get("/api/alerts/00000000-0000-0000-0000-000000000000")
        assert resp.status_code == 404

    def test_returns_alert_by_id(self, db, client):
        alert = make_alert(db, title="Findable Alert")
        db.commit()

        resp = client.get(f"/api/alerts/{alert.id}")

        assert resp.status_code == 200
        assert resp.json()["title"] == "Findable Alert"


class TestUpdateAlert:
    def test_marks_alert_reviewed(self, db, client):
        alert = make_alert(db, reviewed=False)
        db.commit()

        resp = client.patch(f"/api/alerts/{alert.id}", json={"reviewed": True, "status": "approved"})

        assert resp.status_code == 200
        body = resp.json()
        assert body["reviewed"] is True
        assert body["status"] == "approved"

    def test_returns_404_for_unknown_id(self, client):
        resp = client.patch("/api/alerts/00000000-0000-0000-0000-000000000000", json={"reviewed": True})
        assert resp.status_code == 404
