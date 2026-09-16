from __future__ import annotations

from nntpintel.statistics_http import _canonical_request


def test_canonical_request_sorts_query_parameters_and_values() -> None:
    first = _canonical_request(
        "/api/v1/statistics/servers",
        {"resolution": ["day"], "server_id": ["2", "1"]},
    )
    second = _canonical_request(
        "/api/v1/statistics/servers",
        {"server_id": ["1", "2"], "resolution": ["day"]},
    )

    assert first == second
    assert first == "/api/v1/statistics/servers?resolution=day&server_id=1&server_id=2"


def test_canonical_request_without_query_is_path() -> None:
    assert _canonical_request("/api/v1/statistics/topology", {}) == "/api/v1/statistics/topology"
