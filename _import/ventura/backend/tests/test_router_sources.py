from .conftest import make_source


class TestListSources:
    def test_returns_sources_ordered_by_name(self, client, db):
        make_source(db, name="Zebra Source")
        make_source(db, name="Alpha Source")
        db.commit()

        resp = client.get("/api/sources")

        assert resp.status_code == 200
        names = [s["name"] for s in resp.json()]
        assert names == sorted(names)

    def test_empty_registry_returns_empty_list(self, client):
        resp = client.get("/api/sources")
        assert resp.status_code == 200
        assert resp.json() == []


class TestGetSource:
    def test_returns_404_for_unknown_id(self, client):
        resp = client.get("/api/sources/00000000-0000-0000-0000-000000000000")
        assert resp.status_code == 404

    def test_returns_source_by_id(self, client, db):
        source = make_source(db, name="Findable Source")
        db.commit()

        resp = client.get(f"/api/sources/{source.id}")

        assert resp.status_code == 200
        assert resp.json()["name"] == "Findable Source"


class TestCreateSource:
    def test_creates_a_source_with_defaults(self, client):
        resp = client.post(
            "/api/sources",
            json={
                "name": "New Source",
                "source_type": "agenda_center",
                "authority_level": "official_primary",
                "url": "https://example.invalid",
            },
        )

        assert resp.status_code == 201
        body = resp.json()
        assert body["name"] == "New Source"
        assert body["connector"] == "generic"
        assert body["polling_interval_minutes"] == 240

    def test_missing_required_field_is_rejected_with_422(self, client):
        resp = client.post("/api/sources", json={"name": "Incomplete Source"})
        assert resp.status_code == 422


class TestUpdateSource:
    def test_updates_only_the_fields_provided(self, client, db):
        source = make_source(db, name="Original", polling_interval_minutes=240)
        db.commit()

        resp = client.patch(f"/api/sources/{source.id}", json={"enabled": False})

        assert resp.status_code == 200
        body = resp.json()
        assert body["enabled"] is False
        assert body["polling_interval_minutes"] == 240  # untouched

    def test_returns_404_for_unknown_id(self, client):
        resp = client.patch("/api/sources/00000000-0000-0000-0000-000000000000", json={"enabled": False})
        assert resp.status_code == 404
