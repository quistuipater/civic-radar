from datetime import timedelta

from app.archive import now_utc

from .conftest import make_agenda_item, make_meeting


class TestListMeetings:
    def test_filters_by_jurisdiction(self, db, client):
        make_meeting(db, jurisdiction="City of Ventura", body="City Council")
        make_meeting(db, jurisdiction="Ventura County", body="Board of Supervisors")
        db.commit()

        resp = client.get("/api/meetings", params={"jurisdiction": "Ventura County"})

        bodies = [m["body"] for m in resp.json()]
        assert bodies == ["Board of Supervisors"]

    def test_filters_by_body(self, db, client):
        make_meeting(db, body="City Council")
        make_meeting(db, body="Planning Commission")
        db.commit()

        resp = client.get("/api/meetings", params={"body": "Planning Commission"})

        bodies = [m["body"] for m in resp.json()]
        assert bodies == ["Planning Commission"]

    def test_upcoming_only_filters_to_scheduled_status(self, db, client):
        make_meeting(db, status="scheduled", start_time=now_utc() + timedelta(days=3))
        make_meeting(db, status="completed", start_time=now_utc() - timedelta(days=3))
        db.commit()

        resp = client.get("/api/meetings", params={"upcoming_only": True})

        statuses = [m["status"] for m in resp.json()]
        assert statuses == ["scheduled"]


class TestGetMeeting:
    def test_returns_404_for_unknown_id(self, client):
        resp = client.get("/api/meetings/00000000-0000-0000-0000-000000000000")
        assert resp.status_code == 404

    def test_returns_meeting_by_id(self, db, client):
        meeting = make_meeting(db, body="Findable Body")
        db.commit()

        resp = client.get(f"/api/meetings/{meeting.id}")

        assert resp.status_code == 200
        assert resp.json()["body"] == "Findable Body"


class TestListAgendaItems:
    def test_filters_by_meeting_id(self, db, client):
        meeting1 = make_meeting(db)
        meeting2 = make_meeting(db)
        make_agenda_item(db, meeting=meeting1, title="Item on meeting 1")
        make_agenda_item(db, meeting=meeting2, title="Item on meeting 2")
        db.commit()

        resp = client.get("/api/agenda-items", params={"meeting_id": str(meeting1.id)})

        titles = [i["title"] for i in resp.json()]
        assert titles == ["Item on meeting 1"]

    def test_no_filter_returns_all_items(self, db, client):
        meeting = make_meeting(db)
        make_agenda_item(db, meeting=meeting)
        make_agenda_item(db, meeting=meeting)
        db.commit()

        resp = client.get("/api/agenda-items")

        assert len(resp.json()) == 2


class TestGetAgendaItem:
    def test_returns_404_for_unknown_id(self, client):
        resp = client.get("/api/agenda-items/00000000-0000-0000-0000-000000000000")
        assert resp.status_code == 404

    def test_returns_agenda_item_by_id(self, db, client):
        item = make_agenda_item(db, title="Findable Item")
        db.commit()

        resp = client.get(f"/api/agenda-items/{item.id}")

        assert resp.status_code == 200
        assert resp.json()["title"] == "Findable Item"
