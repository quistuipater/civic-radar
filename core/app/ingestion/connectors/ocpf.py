"""Connector for the Massachusetts Office of Campaign and Political Finance
(OCPF) -- the state-level campaign-finance disclosure authority, verified
live 2026-07-10. Massachusetts has no county-level filing officers the way
CA counties do (NetFile serves that role in every CA fork so far), so
netfile_rss.py doesn't apply here; OCPF instead runs its own real,
documented, unauthenticated REST API at api.ocpf.us (Swagger spec at
/swagger/v1/swagger.json).

`base_url` is expected to be `https://api.ocpf.us/reports/log` -- a flat,
unauthenticated JSON feed of the ~50 most recently filed reports
*statewide* (no visible pagination or date-range params on this endpoint;
if Boston-relevant filings ever outpace 50 filings/poll-interval statewide,
some could be missed between polls -- same class of caveat as NetFile's
15-day/1000-item rolling window, just enforced differently). Each row's
`reportId` resolves to a real PDF at `https://api.ocpf.us/report/pdf/{id}`.

Scoped per-source via `CPF_ID_ALLOWLISTS`, keyed by `Source.body` (passed
through as `source_body`) -- each city fork's `electedFilers` allowlist is
its own political geography and shouldn't be conflated. Boston's entry is
the Mayor and 13 City Councilors' `cpfId`s (from `GET /municipalities`,
filtered to the BOSTON entry's `electedFilers` -- verified live 2026-07-10),
not the full set of state legislators/Sheriff/DA whose districts happen to
overlap Boston -- those aren't part of the city government this project
otherwise tracks (Legistar covers City Council; tracking every Suffolk-area
state rep's campaign filings would be real scope creep beyond that).
Re-derive an allowlist from `/municipalities` if a city's elected officials
change (new councilor seated, special election, etc.), or if a source's
`source_body` doesn't match a key here (returns nothing, not an error --
same silent-empty-on-mismatch shape as the rest of this module).
"""

import json

from app.ingestion.connectors.base import DiscoveredDocument

CPF_ID_ALLOWLISTS: dict[str, set[int]] = {
    "Boston": {
        15563,  # Wu, Michelle -- Mayor
        14391,  # Flynn, Edward Michael -- City Councilor
        17092,  # Mejia, Julia M.
        17111,  # Breadon, Elizabeth A.
        18345,  # Durkan, Sharon
        18399,  # Fitzgerald, John
        18447,  # Pepen, Enrique
        18501,  # Weber, Benjamin
        17207,  # Murphy, Erin J.
        17550,  # Worrell, Brian
        17669,  # Louijeune, Ruthzee
        17939,  # Coletta, Gabriela
        18013,  # Culpepper, Miniard
        18331,  # Santana, Henry
    },
    # No Boston-style city government (Mayor/Council) exists here -- these
    # are the state/county-level electedFilers shared by all 6 Martha's
    # Vineyard towns' /municipalities entries (Aquinnah cityCode 104 and
    # Tisbury cityCode 296 both verified live 2026-09-10, identical filer
    # set: MV's towns are too small to have their own OCPF-registered local
    # candidates -- Select Board etc. file with the town clerk, not OCPF).
    "Martha's Vineyard": {
        16300,  # Cyr, Julian Andre -- Senate, Cape & Islands
        17401,  # Moakley, Thomas -- House, Barnstable, Dukes & Nantucket
        16382,  # Ogden, Robert W. -- Sheriff, Dukes County
        17957,  # Galibois, Robert -- DA, Cape & Islands District
    },
}


def discover(json_bytes: bytes, base_url: str, source_body: str | None = None) -> list[DiscoveredDocument]:
    allowlist = CPF_ID_ALLOWLISTS.get(source_body or "", set())
    if not allowlist:
        return []
    try:
        reports = json.loads(json_bytes)
    except (ValueError, TypeError):
        return []
    if not isinstance(reports, list):
        return []

    results: list[DiscoveredDocument] = []
    for report in reports:
        if report.get("cpfId") not in allowlist:
            continue
        report_id = report.get("reportId")
        if report_id is None:
            continue
        filer = report.get("fullNameReverse") or "Unknown filer"
        report_type = report.get("reportTypeDescription") or "Report"
        period = report.get("reportingPeriod")
        title = f"{filer} — {report_type} ({period})" if period else f"{filer} — {report_type}"
        results.append(
            DiscoveredDocument(
                url=f"https://api.ocpf.us/report/pdf/{report_id}",
                document_type="notice",
                title=title,
            )
        )
    return results
