from .conftest import make_document, make_issue


class TestListIssues:
    def test_filters_by_status(self, client, db):
        make_issue(db, title="Open Issue", status="new")
        make_issue(db, title="Closed Issue", status="closed")
        db.commit()

        resp = client.get("/api/issues", params={"status": "closed"})

        assert resp.status_code == 200
        titles = [i["title"] for i in resp.json()]
        assert titles == ["Closed Issue"]

    def test_filters_by_jurisdiction(self, client, db):
        make_issue(db, title="Ventura Issue", jurisdiction="City of Ventura")
        make_issue(db, title="County Issue", jurisdiction="Ventura County")
        db.commit()

        resp = client.get("/api/issues", params={"jurisdiction": "Ventura County"})

        titles = [i["title"] for i in resp.json()]
        assert titles == ["County Issue"]


class TestGetIssue:
    def test_returns_404_for_unknown_id(self, client):
        resp = client.get("/api/issues/00000000-0000-0000-0000-000000000000")
        assert resp.status_code == 404

    def test_returns_issue_by_id(self, client, db):
        issue = make_issue(db, title="Findable Issue")
        db.commit()

        resp = client.get(f"/api/issues/{issue.id}")

        assert resp.status_code == 200
        assert resp.json()["title"] == "Findable Issue"


class TestCreateIssue:
    def test_creates_an_issue(self, client):
        resp = client.post("/api/issues", json={"title": "New Issue", "slug": "new-issue"})

        assert resp.status_code == 201
        assert resp.json()["slug"] == "new-issue"

    def test_duplicate_slug_is_rejected_with_409(self, client, db):
        make_issue(db, slug="taken-slug")
        db.commit()

        resp = client.post("/api/issues", json={"title": "Another Issue", "slug": "taken-slug"})

        assert resp.status_code == 409


class TestUpdateIssue:
    def test_updates_only_the_fields_provided(self, client, db):
        issue = make_issue(db, title="Original Title", status="new")
        db.commit()

        resp = client.patch(f"/api/issues/{issue.id}", json={"status": "monitoring"})

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "monitoring"
        assert body["title"] == "Original Title"

    def test_returns_404_for_unknown_id(self, client):
        resp = client.patch("/api/issues/00000000-0000-0000-0000-000000000000", json={"status": "monitoring"})
        assert resp.status_code == 404


class TestAttachToIssue:
    def test_attaches_a_document_link(self, client, db):
        issue = make_issue(db)
        document = make_document(db)
        db.commit()

        resp = client.post(f"/api/issues/{issue.id}/links", json={"document_id": str(document.id)})

        assert resp.status_code == 201

    def test_requires_either_document_id_or_agenda_item_id(self, client, db):
        issue = make_issue(db)
        db.commit()

        resp = client.post(f"/api/issues/{issue.id}/links", json={})

        assert resp.status_code == 422

    def test_returns_404_for_unknown_issue(self, client):
        resp = client.post(
            "/api/issues/00000000-0000-0000-0000-000000000000/links",
            json={"document_id": "00000000-0000-0000-0000-000000000001"},
        )
        assert resp.status_code == 404


class TestIssueBrief:
    def test_returns_404_for_unknown_issue(self, client):
        resp = client.get("/api/issues/00000000-0000-0000-0000-000000000000/brief.md")
        assert resp.status_code == 404

    def test_returns_markdown_for_a_real_issue(self, client, db):
        issue = make_issue(db, title="Downtown Parking Ordinance")
        db.commit()

        resp = client.get(f"/api/issues/{issue.id}/brief.md")

        assert resp.status_code == 200
        assert "Downtown Parking Ordinance" in resp.text
