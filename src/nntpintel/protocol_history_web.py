from __future__ import annotations

import datetime
from html import escape
from urllib.parse import urlencode

from nntpintel.statistics import protocol_statistics
from nntpintel.statistics_web import _page, _range_form, _range_links, _table, resolve_preset


def _value_filter(values: list[dict], kind: str | None, value: str | None) -> list[dict]:
    filtered = values
    if kind:
        filtered = [item for item in filtered if item.get("kind") == kind]
    if value:
        filtered = [item for item in filtered if item.get("value") == value]
    return filtered


def protocol_history_page(
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
    """Render one server's TLS/protocol capability history from rollups."""
    if server_id <= 0:
        raise ValueError("server_id must be a positive integer")
    if start is None and end is None and preset is not None:
        start, end = resolve_preset(preset, resolution)
    label = range_label or preset or "all-time"
    payload = protocol_statistics(storage, resolution=resolution, start=start, end=end, server_id=server_id)
    rows = payload["rows"]
    values = _value_filter(payload["values"], kind, value)
    host = rows[0].get("host") if rows else f"server {server_id}"
    tls_values = [row.get("tls_ratio") for row in rows if row.get("tls_ratio") is not None]
    avg_tls = f"{sum(tls_values) / len(tls_values):.3f}" if tls_values else "n/a"
    capability_entries = sum(int(row.get("capability_entry_count") or 0) for row in rows)
    path = f"/web/statistics/server/{server_id}/protocol"
    api_query = {"resolution": resolution, "server_id": server_id}
    cards = "".join(
        f'<div class="card"><div class="muted">{escape(label_)}</div><div class="metric">{escape(str(metric))}</div></div>'
        for label_, metric in (("Buckets", len(rows)), ("Avg TLS ratio", avg_tls), ("Capability entries", capability_entries))
    )
    body = f"""
<section><h2>{escape(str(host))} — TLS / protocol history</h2>
<p>Server ID: <strong>{server_id}</strong> · Range: <strong>{escape(label)}</strong> · Resolution: <strong>{escape(resolution)}</strong></p>
<p><a href="/web/statistics">← Overview</a> &nbsp; <a href="/web/statistics/server/{server_id}">Server history</a></p>
<p>{_range_links(path)}</p>
{_range_form(path, resolution, start, end)}
<p><a href="/api/v1/statistics/protocol?{urlencode(api_query)}">JSON API for this server</a></p>
<div class="cards">{cards}</div></section>
{_table("TLS / protocol observations", rows, ("bucket_start", "host", "observation_count", "tls_enabled_count", "tls_ratio", "capabilities_observed_count", "capability_entry_count"))}
{_table("Capability / protocol values", values, ("bucket_start", "host", "kind", "value", "occurrence_count"))}
"""
    if kind or value:
        clear_query = urlencode({"resolution": resolution, "preset": preset or "all-time"})
        body += (
            "<section><p class=\"muted\">Filtered values: "
            f"kind={escape(kind or '*')} value={escape(value or '*')} · "
            f"<a href=\"{path}?{clear_query}\">clear filter</a>"
            "</p></section>"
        )
    return _page(f"Server {server_id} protocol history", body)
