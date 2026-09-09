from __future__ import annotations

from html import escape
from urllib.parse import quote

from nntpintel.propagation_topology_incidents import list_topology_incidents
from nntpintel.storage import Storage


def topology_incidents_page(storage: Storage) -> str:
    incidents = list_topology_incidents(storage)
    open_count = sum(1 for item in incidents if item["status"] == "open")
    critical_count = sum(
        1
        for item in incidents
        if item["status"] == "open" and item["severity"] == "critical"
    )
    caution_count = sum(
        1
        for item in incidents
        if item["status"] != "resolved" and item["evidence_caution"]
    )
    rows = "".join(
        "<tr>"
        f'<td>{item["id"]}</td>'
        f'<td>{escape(str(item["host"]))}</td>'
        f'<td>{escape(str(item["kind"]))}</td>'
        f'<td>{escape(str(item["severity"]))}</td>'
        f'<td>{escape(str(item["status"]))}</td>'
        f'<td>{item["triage_priority_score"]}</td>'
        f'<td>{escape(str(item["evidence_level"]))}</td>'
        f'<td>{item["valid_presence_coverage"]}</td>'
        f'<td>{escape(str(item["freshness"]))}</td>'
        f'<td>{item["impact_score"]}</td>'
        f'<td>{escape(str(item["started_at"]))}</td>'
        f'<td>{escape(str(item["updated_at"]))}</td>'
        f'<td>{escape(str(item["resolved_at"] or ""))}</td>'
        f'<td><a href="/web/propagation/topology/explain/{quote(str(item["conclusion_ref"]), safe="")}">Explain</a></td>'
        "</tr>"
        for item in incidents
    ) or '<tr><td colspan="14">No topology incidents recorded.</td></tr>'
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Topology incidents - NNTPIntel</title>
<style>
:root{{color-scheme:dark;font-family:system-ui,sans-serif}}body{{margin:0;background:#101418;color:#e8edf2}}
header{{padding:1.5rem 2rem;background:#182028;border-bottom:1px solid #2d3944}}main{{padding:1.5rem 2rem 3rem;max-width:1600px;margin:auto}}
a{{color:#9fd3ff}}.cards{{display:flex;gap:1rem;flex-wrap:wrap;margin:1rem 0 2rem}}.card,table{{background:#182028;border:1px solid #2d3944}}.card{{min-width:180px;padding:1rem;border-radius:.6rem}}.metric{{font-size:2rem;font-weight:700}}table{{width:100%;border-collapse:collapse}}th,td{{text-align:left;padding:.65rem;border-bottom:1px solid #2d3944}}th{{color:#a8b5c2}}.warning{{border:1px solid #8a6d1d;background:#2a2412;padding:1rem;border-radius:.5rem}}
</style></head><body><header><h1>NNTPIntel</h1></header><main>
<p><a href="/web/propagation/topology">← Inferred topology</a> · <a href="/web/propagation/topology/evidence#conclusions">Explainable conclusions</a> · <a href="/web/propagation/topology/anomalies">Anomalies</a> · <a href="/web/propagation/topology/impact">Impact / centrality</a> · <a href="/web/propagation/topology/quality">Data quality</a></p>
<h2>Topology incidents</h2>
<p class="warning"><strong>Inference only.</strong> Severity is never reduced by weak evidence. Triage priority combines severity, evidence strength and impact only to order operator attention; it does not prove direct NNTP peering, physical centrality, or operational dependency.</p>
<div class="cards"><div class="card">Open<div class="metric">{open_count}</div></div><div class="card">Critical open<div class="metric">{critical_count}</div></div><div class="card">Evidence caution<div class="metric">{caution_count}</div></div><div class="card">Recorded<div class="metric">{len(incidents)}</div></div></div>
<table><thead><tr><th>ID</th><th>Server</th><th>Type</th><th>Severity</th><th>Status</th><th>Triage</th><th>Evidence</th><th>Coverage</th><th>Freshness</th><th>Impact</th><th>Started</th><th>Updated</th><th>Resolved</th><th></th></tr></thead><tbody>{rows}</tbody></table>
</main></body></html>"""
