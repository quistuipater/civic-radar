"""Tests for the Santa Cruz County Planning Commission legacy-ASP search
ingestion module. The results-page markup here is copied from what was
captured live against www2.santacruzcountyca.gov on 2026-07-10 (see the
module docstring) -- these tests pin down the parsing/session-flow logic
against that real shape.
"""

import httpx

import app.ingestion.scc_planning_search as scc_planning_module
from app.ingestion.scc_planning_search import _parse_results, ingest_scc_planning_search
from app.models import Document, Fetch, Meeting

from .conftest import make_source

# A trimmed but byte-faithful excerpt of the real DisplaySearchResult.ASP
# response body (single long line, inline <B> highlight tags mid-word).
RESULTS_HTML = (
    b"15 Documents Found\n"
    b"<SPAN CLASS='document'>1.<A target='_blank' title='' "
    b"href='../ASP/Display/ASPX/DisplayAgenda.aspx?MeetingDate=1/14/2026&MeetingType=1' >"
    b"Agenda - 1/14/2026</A></SPAN><BR>....All Public Comments...<P>"
    b"<SPAN CLASS='document'>2.<A target='_blank' title='' "
    b"href='../ASP/Display/ASPX/DisplayMinutes.aspx?MeetingDate=2/11/2026&MeetingType=1' >"
    b"Minute - 2/11/2026</A></SPAN><BR>Action: Approve Consent <B>Agenda</B>...<P>"
)

EMPTY_RESULTS_HTML = b"Session has expired.  Please search again."


class FakeResponse:
    def __init__(self, content=b"", status_code=200):
        self.content = content
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("error", request=None, response=None)


class FakeSearchClient:
    def __init__(self, results_html=RESULTS_HTML, doc_bytes_by_url=None, raise_on=None):
        self.results_html = results_html
        self.doc_bytes_by_url = doc_bytes_by_url or {}
        self.raise_on = raise_on or set()
        self.requests: list[tuple[str, str]] = []

    def get(self, url, params=None):
        self.requests.append(("GET", url))
        if "PLNsrchHome" in self.raise_on and "PLNsrchHome" in url:
            raise httpx.ConnectError("connection refused")
        if "DisplayAgenda" in url or "DisplayMinutes" in url:
            default_content = f"<html>fake content for {url}</html>".encode()
            return FakeResponse(content=self.doc_bytes_by_url.get(url, default_content))
        return FakeResponse(content=b"<html>search home</html>")

    def post(self, url, data=None):
        self.requests.append(("POST", url))
        if "QueryPLNIndex" in self.raise_on and "QueryPLNIndex" in url:
            raise httpx.ConnectError("connection refused")
        if "DisplaySearchResult" in url:
            return FakeResponse(content=self.results_html)
        return FakeResponse(content=b"<html>query response</html>")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class TestParseResults:
    def test_parses_real_result_rows(self):
        results = _parse_results(RESULTS_HTML, "https://www2.santacruzcountyca.gov/planning/plnmeetings/Search/")

        assert len(results) == 2
        agenda = next(r for r in results if r["document_type"] == "agenda")
        minutes = next(r for r in results if r["document_type"] == "minutes")
        assert agenda["meeting_date"].isoformat() == "2026-01-14"
        assert minutes["meeting_date"].isoformat() == "2026-02-11"

    def test_resolves_relative_urls_against_base(self):
        results = _parse_results(RESULTS_HTML, "https://www2.santacruzcountyca.gov/planning/plnmeetings/Search/")

        assert all(r["url"].startswith("https://www2.santacruzcountyca.gov/") for r in results)

    def test_no_results_returns_empty_list(self):
        assert _parse_results(EMPTY_RESULTS_HTML, "https://example.invalid/") == []

    def test_duplicate_document_type_and_date_pairs_are_deduped(self):
        doubled = RESULTS_HTML + RESULTS_HTML
        results = _parse_results(doubled, "https://www2.santacruzcountyca.gov/planning/plnmeetings/Search/")

        assert len(results) == 2

    def test_date_shaped_but_invalid_date_is_skipped(self):
        # month=13 is date-shaped enough to match the regex but not a real
        # calendar date -- dateutil raises ParserError (a ValueError
        # subclass), which should be swallowed rather than propagated.
        html = (
            b"<SPAN CLASS='document'>1.<A target='_blank' title='' "
            b"href='../ASP/Display/ASPX/DisplayAgenda.aspx?MeetingDate=13/45/2026&MeetingType=1' >"
            b"Agenda - 13/45/2026</A></SPAN><BR>...<P>"
        )
        assert _parse_results(html, "https://www2.santacruzcountyca.gov/planning/plnmeetings/Search/") == []


class TestIngestSccPlanningSearch:
    def _install(self, monkeypatch, **kwargs):
        fake_client = FakeSearchClient(**kwargs)
        monkeypatch.setattr(scc_planning_module.httpx, "Client", lambda **k: fake_client)
        return fake_client

    def test_creates_documents_and_links_meetings(self, db, archive_root, monkeypatch):
        source = make_source(
            db,
            name="Planning Commission",
            jurisdiction="Santa Cruz County",
            url="https://www2.santacruzcountyca.gov/planning/plnmeetings/Search/PLNsrchHome.asp",
            fetch_method="scc_planning_search",
        )
        self._install(monkeypatch)

        created = ingest_scc_planning_search(db, source)

        assert created == 2
        docs = db.query(Document).filter(Document.source_id == source.id).all()
        assert sorted(d.document_type for d in docs) == ["agenda", "minutes"]
        assert all(d.body == "Planning Commission" for d in docs)

    def test_creates_a_meeting_per_real_date(self, db, archive_root, monkeypatch):
        source = make_source(
            db,
            name="Planning Commission",
            jurisdiction="Santa Cruz County",
            url="https://www2.santacruzcountyca.gov/planning/plnmeetings/Search/PLNsrchHome.asp",
            fetch_method="scc_planning_search",
        )
        self._install(monkeypatch)

        ingest_scc_planning_search(db, source)

        meetings = db.query(Meeting).filter(Meeting.jurisdiction == "Santa Cruz County").all()
        assert len(meetings) == 2
        assert all(m.body == "Planning Commission" for m in meetings)

    def test_agenda_and_minutes_on_different_dates_are_different_meetings(self, db, archive_root, monkeypatch):
        source = make_source(
            db,
            name="Planning Commission",
            jurisdiction="Santa Cruz County",
            url="https://www2.santacruzcountyca.gov/planning/plnmeetings/Search/PLNsrchHome.asp",
            fetch_method="scc_planning_search",
        )
        self._install(monkeypatch)

        ingest_scc_planning_search(db, source)

        meeting_dates = {m.start_time.date() for m in db.query(Meeting).all()}
        assert len(meeting_dates) == 2

    def test_rerunning_dedupes_by_content_hash(self, db, archive_root, monkeypatch):
        source = make_source(
            db,
            name="Planning Commission",
            jurisdiction="Santa Cruz County",
            url="https://www2.santacruzcountyca.gov/planning/plnmeetings/Search/PLNsrchHome.asp",
            fetch_method="scc_planning_search",
        )
        self._install(monkeypatch)

        first = ingest_scc_planning_search(db, source)
        second = ingest_scc_planning_search(db, source)

        assert first == 2
        assert second == 0

    def test_search_home_failure_is_recorded_and_does_not_crash(self, db, archive_root, monkeypatch):
        source = make_source(
            db,
            name="Planning Commission",
            jurisdiction="Santa Cruz County",
            url="https://www2.santacruzcountyca.gov/planning/plnmeetings/Search/PLNsrchHome.asp",
            fetch_method="scc_planning_search",
        )
        self._install(monkeypatch, raise_on={"PLNsrchHome"})

        created = ingest_scc_planning_search(db, source)

        assert created == 0
        assert source.consecutive_failures == 1
        assert source.last_error is not None

    def test_query_failure_is_recorded_and_does_not_crash(self, db, archive_root, monkeypatch):
        source = make_source(
            db,
            name="Planning Commission",
            jurisdiction="Santa Cruz County",
            url="https://www2.santacruzcountyca.gov/planning/plnmeetings/Search/PLNsrchHome.asp",
            fetch_method="scc_planning_search",
        )
        self._install(monkeypatch, raise_on={"QueryPLNIndex"})

        created = ingest_scc_planning_search(db, source)

        assert created == 0
        assert source.consecutive_failures == 1

    def test_document_fetch_failure_for_one_item_does_not_block_the_rest(self, db, archive_root, monkeypatch):
        source = make_source(
            db,
            name="Planning Commission",
            jurisdiction="Santa Cruz County",
            url="https://www2.santacruzcountyca.gov/planning/plnmeetings/Search/PLNsrchHome.asp",
            fetch_method="scc_planning_search",
        )

        class FlakyClient(FakeSearchClient):
            def get(self, url, params=None):
                if "DisplayAgenda" in url:
                    raise httpx.ConnectError("connection refused")
                return super().get(url, params=params)

        monkeypatch.setattr(scc_planning_module.httpx, "Client", lambda **k: FlakyClient())

        created = ingest_scc_planning_search(db, source)

        assert created == 1  # only the minutes item made it through

    def test_empty_results_marks_fetch_validation_status_empty(self, db, archive_root, monkeypatch):
        source = make_source(
            db,
            name="Planning Commission",
            jurisdiction="Santa Cruz County",
            url="https://www2.santacruzcountyca.gov/planning/plnmeetings/Search/PLNsrchHome.asp",
            fetch_method="scc_planning_search",
        )
        self._install(monkeypatch, results_html=EMPTY_RESULTS_HTML)

        created = ingest_scc_planning_search(db, source)

        assert created == 0
        fetch = db.query(Fetch).filter(Fetch.source_id == source.id).order_by(Fetch.fetched_at.desc()).first()
        assert fetch.validation_status == "empty"

    def test_updates_source_bookkeeping_on_success(self, db, archive_root, monkeypatch):
        source = make_source(
            db,
            name="Planning Commission",
            jurisdiction="Santa Cruz County",
            url="https://www2.santacruzcountyca.gov/planning/plnmeetings/Search/PLNsrchHome.asp",
            fetch_method="scc_planning_search",
        )
        self._install(monkeypatch)

        ingest_scc_planning_search(db, source)

        assert source.last_fetched_at is not None
        assert source.consecutive_failures == 0
        assert source.last_error is None
        assert source.last_changed_at is not None
