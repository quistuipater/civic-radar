"""Tests for the OCPF connector's per-source allowlist scoping
(CPF_ID_ALLOWLISTS, keyed by Source.body) -- generalized 2026-09-10 when
Martha's Vineyard Civic Radar became the connector's second user; Boston's
allowlist must keep working unchanged and a source with no matching
allowlist must discover nothing, not raise.
"""

import json

from app.ingestion.connectors.ocpf import discover


def make_report(cpf_id: int, report_id: int = 999) -> dict:
    return {
        "cpfId": cpf_id,
        "reportId": report_id,
        "fullNameReverse": "Doe, Jane",
        "reportTypeDescription": "Year-End Report",
        "reportingPeriod": "2026",
    }


class TestDiscover:
    def test_boston_allowlist_matches_a_known_filer(self):
        reports = [make_report(15563)]  # Wu, Michelle -- Mayor

        found = discover(json.dumps(reports).encode(), "https://api.ocpf.us/reports/log", source_body="Boston")

        assert len(found) == 1
        assert found[0].url == "https://api.ocpf.us/report/pdf/999"

    def test_marthas_vineyard_allowlist_matches_a_known_filer(self):
        reports = [make_report(16382)]  # Ogden, Robert W. -- Sheriff, Dukes County

        found = discover(
            json.dumps(reports).encode(), "https://api.ocpf.us/reports/log", source_body="Martha's Vineyard"
        )

        assert len(found) == 1

    def test_a_filer_not_on_the_matching_allowlist_is_excluded(self):
        reports = [make_report(99999)]

        found = discover(json.dumps(reports).encode(), "https://api.ocpf.us/reports/log", source_body="Boston")

        assert found == []

    def test_boston_filer_does_not_leak_into_marthas_vineyard_results(self):
        reports = [make_report(15563)]  # Wu, Michelle -- Boston Mayor only

        found = discover(
            json.dumps(reports).encode(), "https://api.ocpf.us/reports/log", source_body="Martha's Vineyard"
        )

        assert found == []

    def test_unknown_source_body_discovers_nothing_rather_than_raising(self):
        reports = [make_report(15563)]

        found = discover(json.dumps(reports).encode(), "https://api.ocpf.us/reports/log", source_body="Nowhere")

        assert found == []

    def test_missing_source_body_discovers_nothing_rather_than_raising(self):
        reports = [make_report(15563)]

        found = discover(json.dumps(reports).encode(), "https://api.ocpf.us/reports/log", source_body=None)

        assert found == []
