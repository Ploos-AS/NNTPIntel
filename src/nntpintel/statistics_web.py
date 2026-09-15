from __future__ import annotations

import datetime
from html import escape
from urllib.parse import urlencode

from nntpintel.statistics import (
    group_statistics,
    parse_statistics_time,
    propagation_statistics,
    protocol_statistics,
    server_statistics,
    topology_statistics,
    validate_statistics_range,
)

_STYLE = """
:root { color-scheme: dark; font-family: system-ui, sans-serif; }
body { margin: 0; background: #101418; color: #e8edf2; }
header { padding: 1.5rem 2rem; background: #182028; border-bottom: 1px solid #2d3944; }
main { padding: 1.5rem 2rem 3rem; max-width: 1400px; margin: auto; }
a { color: #9fd3ff; }
nav a { margin-right: 1rem; }
.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 1rem; margin: 1rem 0 2rem; }
.card { background: #182028; border: 1px solid #2d3944; border-radius: .6rem; padding: 1rem; }
.metric { font-size: 2rem; font-weight: 700; }
section { margin: 2rem 0; }
table { width: 100%; border-collapse: collapse; background: #182028; }
th, td { text-align: left; padding: .65rem; border-bottom: 1px solid #2d3944; vertical-align: top; }
th { color: #a8b5c2; }
.muted { color: #8f9ba6; }
code { color: #c9e5ff; white-space: pre-wrap; overflow-wrap: anywhere; }
.range-form { display: flex; flex-wrap: wrap; gap: .65rem; align-items: end; margin: 1rem 0; }
.range-form label { display: grid; gap: .25rem; color: #a8b5c2; }
.range-form input, .range-form select, .range-form button { padding: .45rem .55rem; background: #182028; color: #e8edf2; border: 1px solid #465563; border-radius: .3rem; }
.chart { background: #182028; border: 1px solid #2d3944; border-radius: .6rem; padding: 1rem; overflow-x: auto; }
.chart svg { display: block; width: 100%; min-width: 520px; height: 220px; }
.chart .axis { stroke: #465563; stroke-width: 1; }
.chart .series { fill: none; stroke: #9fd3ff; stroke-width: 2.5; vector-effect: non-scaling-stroke; }
.chart .point { fill: #9fd3ff; }
.server-links { display: flex; flex-wrap: wrap; gap: .6rem; }
.server-links a { display: inline-block; padding: .55rem .75rem; background: #182028; border: 1px solid #2d3944; border-radius: .4rem; }
"""


def _page(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)} - NNTPIntel</title><style>{_STYLE}</style></head>
<body><header><h1>NNTPIntel historical statistics</h1>
<nav><a href="/web/statistics">Overview</a><a href="/api/v1/statistics/servers?resolution=day">Server API</a>
<a href="/api/v1/statistics/groups?resolution=day">Group API</a>
<a href="/api/v1/statistics/protocol?resolution=day">Protocol API</a>
<a href="/api/v1/statistics/propagation?resolution=day">Propagation API</a>
<a href="/api/v1/statistics/topology?resolution=day">Topology API</a></nav></header>
<main>{body}</main></body></html>"""


def _range_links(path: str = "/web/statistics") -> str:
    ranges = (("24h", "hour"), ("7d", "hour"), ("30d", "day"), ("1y", "month"), ("all-time", "month"))
    return " ".join(
        f'<a href="{path}?{urlencode({"preset": label, "resolution": resolution})}">{label}</a>'
        for label, resolution in ranges
    )


def _range_form(path: str, resolution: str, start: datetime.datetime | None, end: datetime.datetime | None) -> str:
    start_value = start.isoformat().replace("+00:00", "Z") if start else ""
    end_value = end.isoformat().replace("+00:00", "Z") if end else ""
    options = "".join(f'<option value="{item}"{" selected" if item == resolution else ""}>{item}</option>' for item in ("hour", "day", "month"))
    return f'''<form class="range-form" method="get" action="{escape(path)}">
<label>Start (ISO 8601)<input name="start" value="{escape(start_value)}" placeholder="2026-01-01T00:00:00Z" required></label>
<label>End (ISO 8601)<input name="end" value="{escape(end_value)}" placeholder="2026-02-01T00:00:00Z" required></label>
<label>Resolution<select name="resolution">{options}</select></label>
<button type="submit">Custom range</button></form>'''


def resolve_preset(preset: str | None, resolution: str) -> tuple[datetime.datetime | None, datetime.datetime | None]:
    if preset in {None, "", "all-time"}: return None, None
    now = datetime.datetime.now(datetime.UTC)
    days = {"24h": 1, "7d": 7, "30d": 30, "1y": 365}.get(preset)
    if days is None: raise ValueError("unknown statistics range preset")
    return now - datetime.timedelta(days=days), now


def resolve_web_range(*, resolution: str, preset: str | None, start_text: str | None = None, end_text: str | None = None) -> tuple[datetime.datetime | None, datetime.datetime | None, str]:
    if start_text or end_text:
        if not start_text or not end_text: raise ValueError("start and end must be supplied together")
        start = parse_statistics_time(start_text); end = parse_statistics_time(end_text)
        window = validate_statistics_range(resolution=resolution, start=start, end=end)
        return window.start, window.end, "custom"
    start, end = resolve_preset(preset, resolution)
    window = validate_statistics_range(resolution=resolution, start=start, end=end)
    return window.start, window.end, preset or "all-time"


def _table(title: str, rows: list[dict], columns: tuple[str, ...]) -> str:
    if not rows: return f"<section><h2>{escape(title)}</h2><p class=\"muted\">No rollup data for this range.</p></section>"
    head = "".join(f"<th>{escape(column)}</th>" for column in columns)
    body = "".join("<tr>" + "".join(f"<td>{escape(str(row.get(column, '')))}</td>" for column in columns) + "</tr>" for row in rows[:100])
    return f"<section><h2>{escape(title)}</h2><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></section>"


def _chart(title: str, rows: list[dict], value_key: str, *, percent: bool = False) -> str:
    values: list[tuple[str, float]] = []
    for row in rows:
        value = row.get(value_key)
        if value is None: continue
        try: values.append((str(row.get("bucket_start", "")), float(value)))
        except (TypeError, ValueError): continue
    if not values: return f'<section><h2>{escape(title)}</h2><p class="muted">No rollup data for this graph.</p></section>'
    width, height, pad = 900.0, 200.0, 28.0
    numeric = [value for _, value in values]; low = 0.0 if percent else min(numeric); high = 1.0 if percent else max(numeric)
    if high <= low: high = low + 1.0
    span_x = width - 2 * pad; span_y = height - 2 * pad; denominator = max(len(values) - 1, 1)
    points = []; circles = []
    for index, (bucket, value) in enumerate(values):
        x = pad + span_x * index / denominator; y = height - pad - span_y * (value - low) / (high - low)
        points.append(f"{x:.1f},{y:.1f}"); circles.append(f'<circle class="point" cx="{x:.1f}" cy="{y:.1f}" r="3"><title>{escape(bucket)}: {value:g}</title></circle>')
    return f'''<section><h2>{escape(title)}</h2><div class="chart"><svg viewBox="0 0 900 220" role="img" aria-label="{escape(title)}"><line class="axis" x1="28" y1="172" x2="872" y2="172"></line><polyline class="series" points="{' '.join(points)}"></polyline>{''.join(circles)}</svg><div class="muted">{escape(values[0][0])} → {escape(values[-1][0])} · {len(values)} rollup buckets</div></div></section>'''


def _server_discovery(rows: list[dict]) -> str:
    servers: dict[int, str] = {}
    for row in rows:
        try: server_id = int(row["server_id"])
        except (KeyError, TypeError, ValueError): continue
        host = str(row.get("host") or f"server {server_id}")
        servers[server_id] = host
    if not servers:
        return '<section><h2>Servers</h2><p class="muted">No servers have rollup data for this range.</p></section>'
    links = "".join(f'<a href="/web/statistics/server/{server_id}">{escape(host)} <span class="muted">#{server_id}</span></a>' for server_id, host in sorted(servers.items(), key=lambda item: (item[1].lower(), item[0])))
    return f'<section><h2>Browse servers</h2><p class="muted">Open a server to inspect availability, latency, groups, protocol/TLS and propagation history.</p><div class="server-links">{links}</div></section>'


def historical_statistics_page(storage: object, *, resolution: str = "day", start: datetime.datetime | None = None, end: datetime.datetime | None = None, preset: str | None = None, range_label: str | None = None) -> str:
    if preset is not None and start is None and end is None: start, end = resolve_preset(preset, resolution)
    servers = server_statistics(storage, resolution=resolution, start=start, end=end)
    group = group_statistics(storage, resolution=resolution, start=start, end=end)
    protocol = protocol_statistics(storage, resolution=resolution, start=start, end=end)
    propagation = propagation_statistics(storage, resolution=resolution, start=start, end=end)
    topology = topology_statistics(storage, resolution=resolution, start=start, end=end)
    cards = "".join(f'<div class="card"><div class="muted">{escape(label)}</div><div class="metric">{escape(str(value))}</div></div>' for label, value in (("Servers", len({row.get("server_id") for row in servers["rows"] if row.get("server_id") is not None})), ("Group buckets", len(group["rows"])), ("Group values", len(group["values"])), ("Protocol buckets", len(protocol["rows"])), ("Propagation buckets", len(propagation["rows"])), ("Propagation campaigns", len(propagation["campaigns"])), ("Topology buckets", len(topology["rows"]))))
    shown_range = range_label or preset or ("custom" if start is not None else "all-time")
    body = f'''<section><h2>Historical overview</h2><p>Range: <strong>{escape(shown_range)}</strong> · Resolution: <strong>{escape(resolution)}</strong></p><p>{_range_links()}</p>{_range_form("/web/statistics", resolution, start, end)}<div class="cards">{cards}</div></section>
{_server_discovery(servers["rows"])}
{_chart("TLS ratio trend", protocol["rows"], "tls_ratio", percent=True)}
{_chart("Propagation presence trend", propagation["rows"], "presence_ratio", percent=True)}
{_chart("Topology incident trend", topology["rows"], "incident_started_count")}
{_table("Group / hierarchy rollups", group["rows"], ("bucket_start", "server_id", "inventory_count", "observed_group_count", "observed_hierarchy_count", "event_count"))}
{_table("Protocol / TLS rollups", protocol["rows"], ("bucket_start", "server_id", "observation_count", "tls_enabled_count", "tls_ratio", "capability_entry_count"))}
{_table("Propagation rollups", propagation["rows"], ("bucket_start", "server_id", "probe_count", "present_count", "absent_count", "presence_ratio", "incident_started_count"))}
{_table("Propagation campaigns", propagation["campaigns"], ("bucket_start", "created_count", "completed_count", "expired_or_closed_count"))}
{_table("Inferred topology rollups", topology["rows"], ("bucket_start", "snapshot_count", "conclusion_count", "incident_started_count"))}'''
    return _page("Historical statistics", body)


def server_history_page(storage: object, server_id: int, *, resolution: str = "hour", preset: str | None = "7d", start: datetime.datetime | None = None, end: datetime.datetime | None = None, range_label: str | None = None) -> str:
    if server_id <= 0: raise ValueError("server_id must be a positive integer")
    if start is None and end is None: start, end = resolve_preset(preset, resolution) if preset is not None else (None, None)
    payload = server_statistics(storage, resolution=resolution, start=start, end=end, server_id=server_id)
    rows = payload["rows"]; host = rows[0].get("host") if rows else f"server {server_id}"
    availability = [row.get("availability_ratio") for row in rows if row.get("availability_ratio") is not None]; latency = [row.get("connect_ms_avg") for row in rows if row.get("connect_ms_avg") is not None]
    cards = "".join(f'<div class="card"><div class="muted">{escape(label)}</div><div class="metric">{escape(str(value))}</div></div>' for label, value in (("Buckets", len(rows)), ("Avg availability", f"{sum(availability) / len(availability):.3f}" if availability else "n/a"), ("Avg connect ms", f"{sum(latency) / len(latency):.1f}" if latency else "n/a")))
    path = f"/web/statistics/server/{server_id}"; shown_range = range_label or ("custom" if start is not None and preset is None else preset or "all-time")
    body = f'''<section><h2>{escape(str(host))}</h2><p>Server ID: <strong>{server_id}</strong> · Range: <strong>{escape(shown_range)}</strong> · Resolution: <strong>{escape(resolution)}</strong></p>
<p><a href="/web/statistics">← Overview</a> &nbsp; {_range_links(path)}</p>
<p><strong>Explore:</strong> <a href="{path}/groups">Groups / hierarchies</a> &nbsp; <a href="{path}/protocol">Protocol / TLS</a> &nbsp; <a href="{path}/propagation">Propagation</a></p>
{_range_form(path, resolution, start, end)}<div class="cards">{cards}</div></section>
{_chart("Availability trend", rows, "availability_ratio", percent=True)}
{_chart("Connection latency trend", rows, "connect_ms_avg")}
{_table("Availability and latency history", rows, ("bucket_start", "server_id", "host", "observation_count", "success_count", "failure_count", "availability_ratio", "connect_ms_count", "connect_ms_avg", "connect_ms_min", "connect_ms_max"))}'''
    return _page(f"Server {server_id} history", body)
