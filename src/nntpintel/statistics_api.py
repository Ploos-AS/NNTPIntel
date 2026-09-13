from __future__ import annotations

from collections.abc import Mapping, Sequence

from nntpintel.statistics import (
    group_statistics,
    parse_statistics_time,
    protocol_statistics,
    server_statistics,
)


def _single(params: Mapping[str, Sequence[str]], name: str) -> str | None:
    values = params.get(name, ())
    if not values:
        return None
    if len(values) != 1:
        raise ValueError(f"{name} must be specified once")
    return values[0]


def _statistics_request_args(params: Mapping[str, Sequence[str]]) -> dict:
    resolution = _single(params, "resolution")
    if not resolution:
        raise ValueError("resolution is required")

    start_text = _single(params, "start")
    end_text = _single(params, "end")
    start = parse_statistics_time(start_text) if start_text else None
    end = parse_statistics_time(end_text) if end_text else None

    server_text = _single(params, "server_id")
    if server_text is None:
        server_id = None
    else:
        try:
            server_id = int(server_text)
        except ValueError as exc:
            raise ValueError("server_id must be a positive integer") from exc
        if server_id <= 0:
            raise ValueError("server_id must be a positive integer")

    return {
        "resolution": resolution,
        "start": start,
        "end": end,
        "server_id": server_id,
    }


def server_statistics_request(storage: object, params: Mapping[str, Sequence[str]]) -> dict:
    return server_statistics(storage, **_statistics_request_args(params))


def group_statistics_request(storage: object, params: Mapping[str, Sequence[str]]) -> dict:
    return group_statistics(storage, **_statistics_request_args(params))


def protocol_statistics_request(storage: object, params: Mapping[str, Sequence[str]]) -> dict:
    return protocol_statistics(storage, **_statistics_request_args(params))
