"""Tests for crime-data ingestion, especially the connector-health validation
logic (items_found / validation_status / validation_message). AGENCY_CONFIG
has no real entries yet in this Santa Cruz scaffold (see
app/ingestion/crime_data.py's module docstring) -- forked from Ventura Civic
Radar, where a real bug was found live: one agency's `created_date` field
turned out to be a bulk-load artifact shared by every row, not a reliable
per-record cursor, and silently failed to filter via `where` at all. These
tests exercise the same validation logic against a config registered per-test
via monkeypatch, so they don't depend on any real agency being configured.
"""

import app.ingestion.crime_data as crime_data_module
from app.ingestion.crime_data import ingest_crime_source
from app.models import CrimeIncident, Fetch

from .conftest import make_source

TEST_AGENCY = "Test Police Department"
TEST_AGENCY_CONFIG = {
    "external_id_field": "GlobalID",
    "created_date_field": None,
    "incident_date_field": "Incident_Date_Start",
    "incident_date_end_field": "Incident_Date_End",
    "field_map": {
        "report_number": "Report_Number",
        "offense_category": "Offense_Category",
        "offense_type": "Offense_Type",
        "generalized_address": "GeneralizedAddress",
        "council_district": "Council_District",
        "beat": "Beat",
        "community_council": "Community_Council",
    },
}

TEST_FEATURE = {
    "GlobalID": "abc-123",
    "Report_Number": "26-00001",
    "Offense_Category": "Larceny Theft",
    "Offense_Type": "Theft From Motor Vehicle",
    "GeneralizedAddress": "100 BLOCK OF MAIN ST",
    "Council_District": 1,
    "Beat": "1A",
    "Community_Council": "Downtown",
    "Incident_Date_Start": 1751000000000,
    "Incident_Date_End": None,
    "created_date": 1783390001724,
}


def _latest_fetch(db, source_id):
    return db.query(Fetch).filter_by(source_id=source_id).order_by(Fetch.fetched_at.desc()).first()


def _register_test_agency(monkeypatch):
    monkeypatch.setitem(crime_data_module.AGENCY_CONFIG, TEST_AGENCY, TEST_AGENCY_CONFIG)


class TestIngestCrimeSource:
    def test_new_features_are_created_and_marked_ok(self, db, archive_root, monkeypatch):
        _register_test_agency(monkeypatch)
        source = make_source(db, name="Test PD", agency=TEST_AGENCY, url="https://example.invalid/pd")
        monkeypatch.setattr(crime_data_module, "fetch_new_features", lambda *a, **k: [TEST_FEATURE])

        created = ingest_crime_source(db, source)

        assert created == 1
        assert db.query(CrimeIncident).filter_by(source_id=source.id).count() == 1
        fetch = _latest_fetch(db, source.id)
        assert fetch.status == "ok"
        assert fetch.validation_status == "ok"
        assert fetch.items_found == 1

    def test_rerunning_with_same_features_dedupes_by_external_id(self, db, archive_root, monkeypatch):
        _register_test_agency(monkeypatch)
        source = make_source(db, name="Test PD", agency=TEST_AGENCY, url="https://example.invalid/pd")
        monkeypatch.setattr(crime_data_module, "fetch_new_features", lambda *a, **k: [TEST_FEATURE])

        first = ingest_crime_source(db, source)
        second = ingest_crime_source(db, source)

        assert first == 1
        assert second == 0
        assert db.query(CrimeIncident).filter_by(source_id=source.id).count() == 1

    def test_empty_response_on_full_refresh_source_is_flagged_not_silently_ok(self, db, archive_root, monkeypatch):
        # A source with created_date_field=None does a full re-fetch every
        # poll -- for those, 0 features back is a real anomaly, not "nothing
        # new today".
        _register_test_agency(monkeypatch)
        source = make_source(db, name="Test PD", agency=TEST_AGENCY, url="https://example.invalid/pd")
        monkeypatch.setattr(crime_data_module, "fetch_new_features", lambda *a, **k: [])

        created = ingest_crime_source(db, source)

        assert created == 0
        fetch = _latest_fetch(db, source.id)
        assert fetch.validation_status == "empty"
        assert fetch.items_found == 0

    def test_response_missing_expected_fields_is_flagged_as_schema_mismatch(self, db, archive_root, monkeypatch):
        _register_test_agency(monkeypatch)
        source = make_source(db, name="Test PD", agency=TEST_AGENCY, url="https://example.invalid/pd")
        broken_feature = {"GlobalID": "abc-123"}  # missing Report_Number, Offense_Category, etc.
        monkeypatch.setattr(crime_data_module, "fetch_new_features", lambda *a, **k: [broken_feature])

        ingest_crime_source(db, source)

        fetch = _latest_fetch(db, source.id)
        assert fetch.validation_status == "schema_mismatch"
        assert "Report_Number" in fetch.validation_message

    def test_unknown_agency_is_flagged_as_error_without_crashing(self, db, archive_root):
        source = make_source(db, name="Mystery Agency Feed", agency="Some Agency Not In Config")

        created = ingest_crime_source(db, source)

        assert created == 0
        fetch = _latest_fetch(db, source.id)
        assert fetch.validation_status == "error"

    def test_fetch_exception_is_caught_and_recorded_as_error(self, db, archive_root, monkeypatch):
        _register_test_agency(monkeypatch)
        source = make_source(db, name="Test PD", agency=TEST_AGENCY, url="https://example.invalid/pd")

        def boom(*a, **k):
            raise RuntimeError("ArcGIS query error: bad where clause")

        monkeypatch.setattr(crime_data_module, "fetch_new_features", boom)

        created = ingest_crime_source(db, source)

        assert created == 0
        fetch = _latest_fetch(db, source.id)
        assert fetch.status == "error"
        assert fetch.validation_status == "error"
        assert source.consecutive_failures == 1

    def test_feature_missing_its_external_id_field_is_skipped_not_counted(self, db, archive_root, monkeypatch):
        _register_test_agency(monkeypatch)
        source = make_source(db, name="Test PD", agency=TEST_AGENCY, url="https://example.invalid/pd")
        broken_feature = {**TEST_FEATURE}
        del broken_feature["GlobalID"]
        monkeypatch.setattr(crime_data_module, "fetch_new_features", lambda *a, **k: [broken_feature])

        created = ingest_crime_source(db, source)

        assert created == 0
        assert db.query(CrimeIncident).filter_by(source_id=source.id).count() == 0


class TestIncrementalSyncCursor:
    """AGENCY_CONFIG has no real agency configured yet in this scaffold, so
    this code path isn't exercised by production config today. Verified here
    via a hypothetical config entry, in case a future agency actually has a
    usable cursor field.
    """

    def test_cursor_is_computed_from_the_latest_ingested_incidents_created_at(self, db, archive_root, monkeypatch):
        fake_config = {
            "external_id_field": "GlobalID",
            "created_date_field": "created_date",
            "incident_date_field": None,
            "incident_date_end_field": None,
            "field_map": {"report_number": "Report_Number"},
        }
        monkeypatch.setitem(crime_data_module.AGENCY_CONFIG, "Fake Agency", fake_config)
        source = make_source(db, name="Fake Feed", agency="Fake Agency", url="https://example.invalid/fake")
        db.add(
            CrimeIncident(
                source_id=source.id,
                agency="Fake Agency",
                external_id="already-ingested",
                source_created_at=crime_data_module._epoch_ms_to_datetime(1700000000000),
            )
        )
        db.commit()

        seen_since = []
        monkeypatch.setattr(
            crime_data_module,
            "fetch_new_features",
            lambda url, since, **k: seen_since.append(since) or [],
        )

        ingest_crime_source(db, source)

        assert seen_since == [1700000000000]

    def test_no_prior_incidents_means_no_cursor_yet(self, db, archive_root, monkeypatch):
        fake_config = {
            "external_id_field": "GlobalID",
            "created_date_field": "created_date",
            "incident_date_field": None,
            "incident_date_end_field": None,
            "field_map": {"report_number": "Report_Number"},
        }
        monkeypatch.setitem(crime_data_module.AGENCY_CONFIG, "Fake Agency", fake_config)
        source = make_source(db, name="Fake Feed", agency="Fake Agency", url="https://example.invalid/fake")
        db.commit()

        seen_since = []
        monkeypatch.setattr(
            crime_data_module,
            "fetch_new_features",
            lambda url, since, **k: seen_since.append(since) or [],
        )

        ingest_crime_source(db, source)

        assert seen_since == [None]

    def test_zero_new_features_on_an_incremental_source_is_ok_not_empty(self, db, archive_root, monkeypatch):
        # Unlike full-refresh sources, 0 new rows since the last poll is the
        # expected steady-state for an incremental source, not an anomaly.
        fake_config = {
            "external_id_field": "GlobalID",
            "created_date_field": "created_date",
            "incident_date_field": None,
            "incident_date_end_field": None,
            "field_map": {"report_number": "Report_Number"},
        }
        monkeypatch.setitem(crime_data_module.AGENCY_CONFIG, "Fake Agency", fake_config)
        source = make_source(db, name="Fake Feed", agency="Fake Agency", url="https://example.invalid/fake")
        db.commit()
        monkeypatch.setattr(crime_data_module, "fetch_new_features", lambda *a, **k: [])

        ingest_crime_source(db, source)

        fetch = _latest_fetch(db, source.id)
        assert fetch.validation_status == "ok"
