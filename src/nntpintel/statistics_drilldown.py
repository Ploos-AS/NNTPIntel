from __future__ import annotations

import datetime

from nntpintel.statistics import _json_rows, _require_postgresql, _utc
from nntpintel.storage_backend import StorageBackend

_MAX_DRILLDOWN_WINDOW = datetime.timedelta(hours=24)
_MAX_DRILLDOWN_ROWS = 500


def server_observation_drilldown(
    storage: StorageBackend,
    *,
    server_id: int,
    start: datetime.datetime,
    end: datetime.datetime,
    limit: int = 100,
) -> dict:
    """Return raw server observations for a deliberately narrow debug window.

    Historical/public statistics stay rollup-backed. This helper is an explicit
    drill-down escape hatch for diagnosis and evidence inspection only.
    """
    _require_postgresql(storage)
    if server_id <= 0:
        raise ValueError("server_id must be a positive integer")
    start_utc = _utc(start)
    end_utc = _utc(end)
    if end_utc <= start_utc:
        raise ValueError("end must be after start")
    if end_utc - start_utc > _MAX_DRILLDOWN_WINDOW:
        raise ValueError("raw drill-down range must not exceed 24 hours")
    if limit <= 0 or limit > _MAX_DRILLDOWN_ROWS:
        raise ValueError("limit must be between 1 and 500")

    query = """
        SELECT o.id, e.server_id, s.host, e.id AS endpoint_id, e.port,
               e.transport, e.starttls, o.observed_at, o.success,
               o.connect_ms, o.greeting_code, o.posting_allowed,
               o.mode_reader_code, o.error
        FROM observations o
        JOIN endpoints e ON e.id = o.endpoint_id
        JOIN servers s ON s.id = e.server_id
        WHERE e.server_id = %s
          AND o.observed_at >= %s
          AND o.observed_at < %s
        ORDER BY o.observed_at DESC, o.id DESC
        LIMIT %s
    """
    with storage.connect() as conn:
        rows = _json_rows(
            conn.execute(query, (server_id, start_utc, end_utc, limit)).fetchall()
        )
    return {
        "api_version": "v1",
        "metric_family": "server_observation_drilldown",
        "source": "observations",
        "server_id": server_id,
        "range": {
            "start": start_utc.isoformat().replace("+00:00", "Z"),
            "end": end_utc.isoformat().replace("+00:00", "Z"),
        },
        "limit": limit,
        "rows": rows,
    }
