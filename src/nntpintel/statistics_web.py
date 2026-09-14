from __future__ import annotations

from html import escape
from urllib.parse import urlencode

from nntpintel.statistics import (
    group_statistics,
    propagation_statistics,
    protocol_statistics,
    topology_statistics,
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


def _range_links() -> str:
    ranges = (("24h", "hour"), ("7d", "hour"), ("30d", "day"), ("1y", "month"), ("all-time", "month"))
    return " ".join(
        f'<a href="/web/statistics?{urlencode({"preset": label, "resolution": resolution})}">{label}</a>'
        for label, resolution in ranges
    )


def _table(title: str, rows: list[dict], columns: tuple[str, ...]) -> str:
    if not rows:
        return f"<section><h2>{escape(title)}</h2><p class=\"muted\">No rollup data for this range.</p></section>"
    head = "".join(f"<th>{escape(column)}</th>" for column in columns)
    body = "".join(
        "<tr>" + "".join(f"<td>{escape(str(row.get(column, '')))}</td>" for column in columns) + "</tr>"
        for row in rows[:100]
    )
    return f"<section><h2>{escape(title)}</h2><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></section>"


def historical_statistics_page(
    storage: object,
    *,
    resolution: str = "day",
    start=None,
    end=None,
) -> str:
    """Render the production historical-statistics landing page from rollups only."""
    group = group_statistics(storage, resolution=resolution, start=start, end=end)
    protocol = protocol_statistics(storage, resolution=resolution, start=start, end=end)
    propagation = propagation_statistics(storage, resolution=resolution, start=start, end=end)
    topology = topology_statistics(storage, resolution=resolution, start=start, end=end)

    cards = "".join(
        f'<div class="card"><div class="muted">{escape(label)}</div><div class="metric">{escape(str(value))}</div></div>'
        for label, value in (
            ("Group buckets", len(group["rows"])),
            ("Group values", len(group["values"])),
            ("Protocol buckets", len(protocol["rows"])),
            ("Propagation buckets", len(propagation["rows"])),
            ("Propagation campaigns", len(propagation["campaigns"])),
            ("Topology buckets", len(topology["rows"])),
        )
    )
    body = f"""
<section><h2>Historical overview</h2>
<p>Resolution: <strong>{escape(resolution)}</strong></p>
<p>{_range_links()}</p>
<div class="cards">{cards}</div></section>
{_table("Group / hierarchy rollups", group["rows"], ("bucket_start", "server_id", "inventory_count", "observed_group_count", "observed_hierarchy_count", "event_count"))}
{_table("Protocol / TLS rollups", protocol["rows"], ("bucket_start", "server_id", "observation_count", "tls_enabled_count", "tls_ratio", "capability_entry_count"))}
{_table("Propagation rollups", propagation["rows"], ("bucket_start", "server_id", "probe_count", "present_count", "absent_count", "presence_ratio", "incident_started_count"))}
{_table("Propagation campaigns", propagation["campaigns"], ("bucket_start", "created_count", "completed_count", "expired_or_closed_count"))}
{_table("Inferred topology rollups", topology["rows"], ("bucket_start", "snapshot_count", "conclusion_count", "incident_started_count"))}
"""
    return _page("Historical statistics", body)
