from __future__ import annotations

from html import escape

from nntpintel.propagation_topology_overview import topology_overview
from nntpintel.storage import Storage


def overview_page(storage: Storage) -> str:
    overview = topology_overview(storage)
    signals = overview["signals"]
    topology = overview["topology"]
    quality = overview["data_quality"]
    attention_rows = "".join(
        "<tr>"
        f'<td>{item["priority"]}</td>'
        f'<td>{escape(str(item["kind"]))}</td>'
        f'<td>{escape(str(item["label"]))}</td>'
        f'<td>{escape(str(item["detail"]))}</td>'
        f'<td>{escape(str(item["evidence_level"]))}</td>'
        "</tr>"
        for item in overview["attention"]
    ) or '<tr><td colspan="5" class="muted">No current topology items require elevated attention.</td></tr>'
    server_rows = "".join(
        "<tr>"
        f'<td>{escape(str(item["host"]))}</td>'
        f'<td>{item["risk_score"]}</td>'
        f'<td>{escape(str(item["risk_level"]))}</td>'
        f'<td>{escape(str(item["evidence_level"]))}</td>'
        f'<td>{item["open_incident_count"]}</td>'
        f'<td>{"yes" if item["is_gateway"] else "no"}</td>'
        "</tr>"
        for item in overview["top_servers"]
    ) or '<tr><td colspan="6" class="muted">No inferred topology servers yet.</td></tr>'
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Topology executive overview - NNTPIntel</title><style>
:root {{ color-scheme:dark;font-family:system-ui,sans-serif; }} body {{ margin:0;background:#101418;color:#e8edf2; }}
header {{ padding:1.5rem 2rem;background:#182028;border-bottom:1px solid #2d3944; }} main {{ padding:1.5rem 2rem 3rem;max-width:1400px;margin:auto; }}
a {{ color:#9fd3ff; }} nav a {{ margin-right:1rem; }} .cards {{ display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:1rem;margin:1rem 0 2rem; }}
.card,table {{ background:#182028;border:1px solid #2d3944; }} .card {{ border-radius:.6rem;padding:1rem; }} .metric {{ font-size:2rem;font-weight:700; }}
table {{ width:100%;border-collapse:collapse;margin-bottom:2rem; }} th,td {{ text-align:left;padding:.65rem;border-bottom:1px solid #2d3944; }} th,.muted {{ color:#a8b5c2; }}
.warning {{ padding:1rem;border:1px solid #8a6f2a;background:#2a2416;border-radius:.6rem; }}
</style></head><body><header><h1>NNTPIntel</h1><nav><a href="/">Dashboard</a><a href="/web/servers">Servers</a><a href="/web/groups">Groups</a><a href="/web/events">Events</a><a href="/web/propagation">Propagation</a></nav></header><main>
<p><a href="/web/propagation/topology">← Topology</a> · <a href="/web/propagation/topology/risk">Risk synthesis</a> · <a href="/web/propagation/topology/quality">Data quality</a> · <a href="/web/propagation/topology/incidents">Incidents</a> · <a href="/web/propagation/topology/anomalies">Anomalies</a></p>
<h2>Topology executive overview</h2><div class="warning"><strong>Triage only.</strong> {escape(str(overview["disclaimer"]))}</div>
<div class="cards"><div class="card"><div class="muted">Posture</div><div class="metric">{escape(str(overview["posture"]))}</div></div>
<div class="card"><div class="muted">Data quality</div><div class="metric">{quality["score"]}</div>{escape(str(quality["level"]))}</div>
<div class="card"><div class="muted">High-risk / weak evidence</div><div class="metric">{quality["high_risk_low_evidence_server_count"]}</div></div>
<div class="card"><div class="muted">Nodes / edges</div><div class="metric">{topology["node_count"]} / {topology["edge_count"]}</div></div>
<div class="card"><div class="muted">Open incidents</div><div class="metric">{signals["open_incident_count"]}</div></div>
<div class="card"><div class="muted">Anomalies</div><div class="metric">{signals["anomaly_count"]}</div></div>
<div class="card"><div class="muted">High-risk servers</div><div class="metric">{signals["high_risk_server_count"]}</div></div>
<div class="card"><div class="muted">Incident scope</div><div class="metric">{escape(str(signals["incident_scope"]))}</div></div></div>
<h2>What needs attention now</h2><table><thead><tr><th>Priority</th><th>Signal</th><th>Target</th><th>Why</th><th>Evidence</th></tr></thead><tbody>{attention_rows}</tbody></table>
<h2>Highest-priority servers</h2><table><thead><tr><th>Server</th><th>Risk</th><th>Level</th><th>Evidence</th><th>Incidents</th><th>Gateway</th></tr></thead><tbody>{server_rows}</tbody></table>
<p><strong>Risk scores are not quality-adjusted.</strong> Weak or stale evidence lowers confidence in interpretation, not the risk score.</p>
<p class="muted">Communities: {topology["community_count"]} · Gateways: {topology["gateway_server_count"]} · Critical incidents: {signals["critical_incident_count"]} · Recovering incidents: {signals["recovering_incident_count"]} · Critical resilience nodes: {signals["critical_resilience_node_count"]}</p>
</main></body></html>"""
