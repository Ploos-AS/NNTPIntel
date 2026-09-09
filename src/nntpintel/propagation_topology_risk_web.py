from __future__ import annotations

from html import escape
from urllib.parse import quote

from nntpintel.propagation_topology_risk import topology_risk
from nntpintel.storage import Storage


def risk_page(storage: Storage) -> str:
    data = topology_risk(storage)
    server_rows = "".join(
        "<tr>"
        f'<td>{escape(str(item["host"]))}</td>'
        f'<td>{item["community_id"] if item["community_id"] is not None else ""}</td>'
        f'<td>{item["risk_score"]}</td>'
        f'<td>{escape(str(item["risk_level"]))}</td>'
        f'<td>{escape(str(item["evidence_level"]))}</td>'
        f'<td>{item["evidence_coverage"]}</td>'
        f'<td>{escape(str(item["evidence_freshness"]))}</td>'
        f'<td>{item["open_incident_count"]}</td>'
        f'<td>{item["impact_score"]}</td>'
        f'<td>{item["resilience_score"]}</td>'
        f'<td>{item["gateway_score"]}</td>'
        f'<td><a href="/web/propagation/topology/explain/{quote(str(item["conclusion_ref"]), safe="")}">Explain</a></td>'
        "</tr>"
        for item in data["servers"]
    ) or '<tr><td colspan="12">No topology risk data yet.</td></tr>'
    community_rows = "".join(
        "<tr>"
        f'<td>{item["community_id"]}</td>'
        f'<td>{item["risk_score"]}</td>'
        f'<td>{escape(str(item["risk_level"]))}</td>'
        f'<td>{escape(str(item["evidence_level"]))}</td>'
        f'<td>{item["server_count"]}</td>'
        f'<td>{item["open_incident_count"]}</td>'
        f'<td>{item["affected_server_count"]}</td>'
        f'<td>{item["gateway_server_count"]}</td>'
        f'<td><a href="/web/propagation/topology/explain/{quote(str(item["conclusion_ref"]), safe="")}">Explain</a></td>'
        "</tr>"
        for item in data["communities"]
    ) or '<tr><td colspan="9">No topology communities yet.</td></tr>'
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Topology risk synthesis - NNTPIntel</title><style>
:root{{color-scheme:dark;font-family:system-ui,sans-serif}}body{{margin:0;background:#101418;color:#e8edf2}}
header{{padding:1.5rem 2rem;background:#182028;border-bottom:1px solid #2d3944}}main{{padding:1.5rem 2rem 3rem;max-width:1400px;margin:auto}}
a{{color:#9fd3ff}}.cards{{display:flex;gap:1rem;flex-wrap:wrap;margin:1rem 0 2rem}}.card,table{{background:#182028;border:1px solid #2d3944}}.card{{min-width:180px;padding:1rem;border-radius:.6rem}}.metric{{font-size:2rem;font-weight:700}}table{{width:100%;border-collapse:collapse;margin-bottom:2rem}}th,td{{text-align:left;padding:.65rem;border-bottom:1px solid #2d3944}}th{{color:#a8b5c2}}.warning{{border:1px solid #8a6d1d;background:#2a2412;padding:1rem;border-radius:.5rem}}
</style></head><body><header><h1>NNTPIntel</h1></header><main>
<p><a href="/web/propagation/topology">← Inferred topology</a> · <a href="/web/propagation/topology/conclusions">Explainable conclusions</a> · <a href="/web/propagation/topology/quality">Data quality</a> · <a href="/web/propagation/topology/resilience">Resilience</a> · <a href="/web/propagation/topology/incidents">Incidents</a></p>
<h2>Topology risk synthesis</h2>
<p class="warning"><strong>Triage only.</strong> {escape(data["disclaimer"])}</p>
<div class="cards"><div class="card">Incident scope<div class="metric">{escape(str(data["incident_scope"]))}</div></div><div class="card">High-risk servers<div class="metric">{data["high_risk_server_count"]}</div></div><div class="card">High-risk / weak evidence<div class="metric">{data["high_risk_low_evidence_server_count"]}</div></div><div class="card">Data quality<div class="metric">{data["data_quality_score"]}</div>{escape(str(data["data_quality_level"]))}</div><div class="card">High-risk communities<div class="metric">{data["high_risk_community_count"]}</div></div></div>
<h3>Server priority</h3><table><thead><tr><th>Server</th><th>Cluster</th><th>Risk</th><th>Level</th><th>Evidence</th><th>Coverage</th><th>Freshness</th><th>Incidents</th><th>Impact</th><th>Resilience</th><th>Gateway</th><th></th></tr></thead><tbody>{server_rows}</tbody></table>
<h3>Community priority</h3><table><thead><tr><th>Cluster</th><th>Risk</th><th>Level</th><th>Evidence</th><th>Servers</th><th>Incidents</th><th>Affected servers</th><th>Gateways</th><th></th></tr></thead><tbody>{community_rows}</tbody></table>
<p><strong>Risk scores are not quality-adjusted.</strong> Evidence quality changes certainty, not the risk score itself.</p>
</main></body></html>"""
