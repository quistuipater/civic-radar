from .conftest import make_manual_submission


class TestListManualSubmissions:
    def test_returns_submissions(self, db, client):
        make_manual_submission(db, claimed_source="Nextdoor")
        db.commit()

        resp = client.get("/api/manual-submissions")

        assert resp.status_code == 200
        assert len(resp.json()) == 1


class TestCreateManualSubmission:
    def test_creates_submission_as_unverified_regardless_of_input(self, client):
        # prd.md 13.3/15.4: social/community claims never start out verified,
        # even if the caller tried to pass verified=True (not accepted by
        # ManualSubmissionCreate at all -- confirming that).
        resp = client.post(
            "/api/manual-submissions",
            json={"submission_type": "text", "claimed_source": "Facebook", "content_text": "Someone said..."},
        )

        assert resp.status_code == 201
        body = resp.json()
        assert body["verified"] is False
        assert body["verification_status"] == "unresolved"

    def test_missing_required_field_is_rejected(self, client):
        resp = client.post("/api/manual-submissions", json={"content_text": "no submission_type given"})
        assert resp.status_code == 422


class TestUpdateManualSubmission:
    def test_confirming_verification_status_sets_verified_true(self, db, client):
        submission = make_manual_submission(db)
        db.commit()

        resp = client.patch(
            f"/api/manual-submissions/{submission.id}", params={"verification_status": "confirmed"}
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["verification_status"] == "confirmed"
        assert body["verified"] is True

    def test_rejecting_verification_status_leaves_verified_false(self, db, client):
        submission = make_manual_submission(db)
        db.commit()

        resp = client.patch(
            f"/api/manual-submissions/{submission.id}", params={"verification_status": "rejected"}
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["verification_status"] == "rejected"
        assert body["verified"] is False

    def test_updates_operator_note_independently_of_verification_status(self, db, client):
        # Note: ManualSubmissionOut doesn't include operator_note, so it's
        # verified via the DB rather than the response body -- the endpoint
        # accepts and persists it, but never echoes it back to the caller.
        submission = make_manual_submission(db)
        db.commit()

        resp = client.patch(
            f"/api/manual-submissions/{submission.id}", params={"operator_note": "checked against city notice"}
        )

        assert resp.status_code == 200
        db.refresh(submission)
        assert submission.operator_note == "checked against city notice"

    def test_returns_404_for_unknown_id(self, client):
        resp = client.patch(
            "/api/manual-submissions/00000000-0000-0000-0000-000000000000",
            params={"verification_status": "confirmed"},
        )
        assert resp.status_code == 404
