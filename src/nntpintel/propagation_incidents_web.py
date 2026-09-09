from __future__ import annotations

from html import escape

from nntpintel.propagation_incidents import list_propagation_incidents
from nntpintel.storage import Storage


def incidents_page(storage: Storage) -> str:
    incidents = list_propagation_incidents(storage)
    open_count = sum(1 for item in incidents if item["status"] == "open")
    critical_count = sum(
        1
        for item in incidents
        if item["status"] == "open" and item["severity"] == "critical"
    )
    rows = "".join(
        "<tr>"
        f'<td>{item["id"]}</td>'
        f'<td>{escape(str(item["host"]))}</td>'
        f'<td>{escape(str(item["kind"]))}</td>'
        f'<td>{escape(str(item["severity"]))}</td>'
        f'<td>{escape(str(item["status"]))}</td>'
        f'<td>{escape(str(item["started_at"]))}</td>'
        f'<td>{escape(str(item["resolved_at"] or ""))}</td>'
        f'<td>{escape(str(item["metric_value"] if item["metric_value"] is not None else ""))}</td>'
        f'<td>{escape(str(item["baseline_value"] if item["baseline_value"] is not None else ""))}</td>'
        "</tr>"
        for item in incidents
    ) or '<tr><td colspan="9">No propagation incidents recorded.</td></tr>'
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Propagation incidents - NNTPIntel</title>
<style>
:root {{ color-scheme: dark; font-family: system-ui, sans-serif; }}
body {{ margin:0; background:#101418; color:#e8edf2; }}
header {{ padding:1.5rem 2rem; background:#182028; border-bottom:1px solid #2d3944; }}
main {{ max-width:1400px; margin:auto; padding:1.5rem 2rem 3rem; }}
a {{ color:#9fd3ff; }} .cards {{ display:flex; gap:1rem; margin:1rem 0 2rem; flex-wrap:wrap; }}
.card {{ min-width:180px; background:#182028; border:1px solid #2d3944; border-radius:.6rem; padding:1rem; }}
.metric {{ font-size:2rem; font-weight:700; }} table {{ width:100%; border-collapse:collapse; background:#182028; border:1px solid #2d3944; }}
th,td {{ text-align:left; padding:.65rem; border-bottom:1px solid #2d3944; }} th {{ color:#a8b5c2; }}
</style></head><body><header><h1>NNTPIntel</h1><nav><a href="/">Dashboard</a> · <a href="/web/propagation">Propagation</a> · <a href="/web/propagation/trends">Trends</a></nav></header>
<main><h2>Propagation incidents</h2><div class="cards"><div class="card">Open<div class="metric">{open_count}</div></div><div class="card">Critical open<div class="metric">{critical_count}</div></div><div class="card">Recorded<div class="metric">{len(incidents)}</div></div></div>
<table><thead><tr><th>ID</th><th>Server</th><th>Type</th><th>Severity</th><th>Status</th><th>Started</th><th>Resolved</th><th>Metric</th><th>Baseline</th></tr></thead><tbody>{rows}</tbody></table></main></body></html>"""
