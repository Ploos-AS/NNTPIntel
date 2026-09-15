from __future__ import annotations

import datetime
from html import escape
from urllib.parse import urlencode

from nntpintel.statistics import propagation_statistics
from nntpintel.statistics_web import _page, _range_form, _range_links, _table, resolve_preset


def _value_filter(values: list[dict], kind: str | None, value: str | None) -> list[dict]:
    filtered = values
    if kind:
        filtered = [item for item in filtered if item.get("kind") == kind]
    if value:
        filtered = [item for item in filtered if item.get("value") == value]
    return filtered


def propagation_history_page(
    storage: object,
    server_id: int,
    *,
    resolution: str = "day",
    preset: str | None = "30d",
    start: datetime.datetime | None = None,
    end: datetime.datetime | None = None,
    range_label: str | None = None,
    kind: str | None = None,
    value: str | None = None,
) -> str:
    """Render one server's propagation and incident history from rollups."""
    if server_id <= 0:
        raise ValueError("server_id must be a positive integer")
    if start is None and end is None and preset is not None:
        start, end = resolve_preset(preset, resolution)
    label = range_label or preset or "all-time"
    payload = propagation_statistics(storage, resolution=resolution, start=start, end=end, server_id=server_id)
    rows = payload["rows"]
    values = _value_filter(payload["values"], kind, value)
    campaigns = payload["campaigns"]
    host = rows[0].get("host") if rows else f"server {server_id}"
    ratios = [row.get("presence_ratio") for row in rows if row.get("presence_ratio") is not None]
    avg_presence = f"{sum(ratios) / len(ratios):.3f}" if ratios else "n/a"
    incidents = sum(int(row.get("incident_started_count") or 0) for row in rows)
    probes = sum(int(row.get("probe_count") or 0) for row in rows)
    path = f"/web/statistics/server/{server_id}/propagation"
    api_query = {"resolution": resolution, "server_id": server_id}
    cards = "".join(
        f'<div class="card"><div class="muted">{escape(label_)}</div><div class="metric">{escape(str(metric))}</div></div>'
        for label_, metric in (("Buckets", len(rows)), ("Avg presence ratio", avg_presence), ("Probes", probes), ("Incidents started", incidents))
    )
    body = f"""
<section><h2>{escape(str(host))} — propagation history</h2>
<p>Server ID: <strong>{server_id}</strong> · Range: <strong>{escape(label)}</strong> · Resolution: <strong>{escape(resolution)}</strong></p>
<p><a href="/web/statistics">← Overview</a> &nbsp; <a href="/web/statistics/server/{server_id}">Server history</a></p>
<p>{_range_links(path)}</p>
{_range_form(path, resolution, start, end)}
<p><a href="/api/v1/statistics/propagation?{urlencode(api_query)}">JSON API for this server</a></p>
<div class="cards">{cards}</div></section>
{_table("Propagation / incident trend", rows, ("bucket_start", "host", "probe_count", "present_count", "absent_count", "unknown_count", "presence_ratio", "article_count", "first_seen_delay_avg_seconds", "incident_started_count"))}
{_table("Propagation values", values, ("bucket_start", "host", "kind", "value", "occurrence_count"))}
{_table("Global campaign trend", campaigns, ("bucket_start", "created_count", "completed_count", "expired_or_closed_count"))}
"""
    if kind or value:
        clear_query = urlencode({"resolution": resolution, "preset": preset or "all-time"})
        body += (
            "<section><p class=\"muted\">Filtered values: "
            f"kind={escape(kind or '*')} value={escape(value or '*')} · "
            f"<a href=\"{path}?{clear_query}\">clear filter</a>"
            "</p></section>"
        )
    return _page(f"Server {server_id} propagation history", body)
