from __future__ import annotations

from html import escape
from urllib.parse import urlencode

from nntpintel.statistics import topology_statistics
from nntpintel.statistics_web import _page, _range_links, _table, resolve_preset


def _value_filter(values: list[dict], kind: str | None, value: str | None) -> list[dict]:
    filtered = values
    if kind:
        filtered = [item for item in filtered if item.get("kind") == kind]
    if value:
        filtered = [item for item in filtered if item.get("value") == value]
    return filtered


def topology_history_page(
    storage: object,
    *,
    resolution: str = "day",
    preset: str | None = "30d",
    kind: str | None = None,
    value: str | None = None,
) -> str:
    """Render global inferred-topology and incident history from rollups."""
    start, end = resolve_preset(preset, resolution) if preset is not None else (None, None)
    payload = topology_statistics(
        storage,
        resolution=resolution,
        start=start,
        end=end,
    )
    rows = payload["rows"]
    values = _value_filter(payload["values"], kind, value)
    snapshots = sum(int(row.get("snapshot_count") or 0) for row in rows)
    conclusions = sum(int(row.get("conclusion_count") or 0) for row in rows)
    incidents = sum(int(row.get("incident_started_count") or 0) for row in rows)
    path = "/web/statistics/topology"
    api_query = {"resolution": resolution}
    cards = "".join(
        f'<div class="card"><div class="muted">{escape(label)}</div><div class="metric">{escape(str(metric))}</div></div>'
        for label, metric in (
            ("Buckets", len(rows)),
            ("Topology snapshots", snapshots),
            ("Conclusions", conclusions),
            ("Incidents started", incidents),
        )
    )
    body = f"""
<section><h2>Global inferred topology history</h2>
<p>Range: <strong>{escape(preset or "all-time")}</strong> · Resolution: <strong>{escape(resolution)}</strong></p>
<p><a href="/web/statistics">← Statistics overview</a></p>
<p>{_range_links(path)}</p>
<p><a href="/api/v1/statistics/topology?{urlencode(api_query)}">JSON API</a></p>
<div class="cards">{cards}</div></section>
{_table("Topology / incident trend", rows, ("bucket_start", "snapshot_count", "conclusion_count", "incident_started_count"))}
{_table("Topology evidence and risk values", values, ("bucket_start", "kind", "value", "occurrence_count"))}
"""
    if kind or value:
        clear_query = urlencode({"resolution": resolution, "preset": preset or "all-time"})
        body += (
            "<section><p class=\"muted\">Filtered values: "
            f"kind={escape(kind or '*')} value={escape(value or '*')} · "
            f"<a href=\"{path}?{clear_query}\">clear filter</a>"
            "</p></section>"
        )
    return _page("Global topology history", body)
