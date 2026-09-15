from __future__ import annotations

import datetime
from html import escape
from urllib.parse import urlencode

from nntpintel.statistics import group_statistics
from nntpintel.statistics_web import _page, _range_form, _range_links, _table, resolve_preset


def _value_filter(values: list[dict], kind: str | None, value: str | None) -> list[dict]:
    filtered = values
    if kind:
        filtered = [item for item in filtered if item.get("kind") == kind]
    if value:
        filtered = [item for item in filtered if item.get("value") == value]
    return filtered


def group_history_page(
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
    """Render one server's hierarchy/newsgroup history from statistical rollups."""
    if server_id <= 0:
        raise ValueError("server_id must be a positive integer")
    if start is None and end is None and preset is not None:
        start, end = resolve_preset(preset, resolution)
    label = range_label or preset or "all-time"
    payload = group_statistics(storage, resolution=resolution, start=start, end=end, server_id=server_id)
    rows = payload["rows"]
    values = _value_filter(payload["values"], kind, value)
    host = rows[0].get("host") if rows else f"server {server_id}"
    path = f"/web/statistics/server/{server_id}/groups"
    query = {"resolution": resolution, "preset": preset or "all-time"}
    if kind:
        query["kind"] = kind
    if value:
        query["value"] = value
    api_query = {"resolution": resolution, "server_id": server_id}
    body = f"""
<section><h2>{escape(str(host))} — hierarchy/newsgroup history</h2>
<p>Server ID: <strong>{server_id}</strong> · Range: <strong>{escape(label)}</strong> · Resolution: <strong>{escape(resolution)}</strong></p>
<p><a href="/web/statistics">← Overview</a> &nbsp; <a href="/web/statistics/server/{server_id}">Server history</a></p>
<p>{_range_links(path)}</p>
{_range_form(path, resolution, start, end)}
<p><a href="/api/v1/statistics/groups?{urlencode(api_query)}">JSON API for this server</a></p>
</section>
{_table("Inventory history", rows, ("bucket_start", "host", "inventory_count", "snapshot_count", "observed_group_count", "observed_hierarchy_count", "event_count"))}
{_table("Hierarchy / group values", values, ("bucket_start", "host", "kind", "value", "occurrence_count"))}
"""
    if kind or value:
        body += (
            "<section><p class=\"muted\">Filtered values: "
            f"kind={escape(kind or '*')} value={escape(value or '*')} · "
            f"<a href=\"{path}?{urlencode(query | {'kind': '', 'value': ''})}\">clear filter</a>"
            "</p></section>"
        )
    return _page(f"Server {server_id} group history", body)
