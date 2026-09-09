from __future__ import annotations

from html import escape

from nntpintel.propagation_topology import inferred_propagation_topology
from nntpintel.storage import Storage


def topology_page(storage: Storage) -> str:
    topology = inferred_propagation_topology(storage)
    node_rows = "".join(
        "<tr>"
        f'<td>{item["server_id"]}</td>'
        f'<td>{escape(str(item["host"]))}</td>'
        "</tr>"
        for item in topology["nodes"]
    ) or '<tr><td colspan="2" class="muted">No topology nodes yet.</td></tr>'
    edge_rows = "".join(
        "<tr>"
        f'<td>{escape(str(item["source_host"]))}</td>'
        f'<td>→</td>'
        f'<td>{escape(str(item["target_host"]))}</td>'
        f'<td>{item["directional_sample_count"]}</td>'
        f'<td>{item["forward_count"]}/{item["reverse_count"]}/{item["tie_count"]}</td>'
        f'<td>{item["confidence"]}</td>'
        f'<td>{item["median_lead_seconds"]}</td>'
        "</tr>"
        for item in topology["edges"]
    ) or '<tr><td colspan="7" class="muted">No inferred edges meet the confidence threshold.</td></tr>'
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Inferred propagation topology - NNTPIntel</title>
<style>
:root {{ color-scheme: dark; font-family: system-ui,sans-serif; }}
body {{ margin:0;background:#101418;color:#e8edf2; }}
header {{ padding:1.5rem 2rem;background:#182028;border-bottom:1px solid #2d3944; }}
main {{ padding:1.5rem 2rem 3rem;max-width:1400px;margin:auto; }}
a {{ color:#9fd3ff; }} nav a {{ margin-right:1rem; }}
.cards {{ display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:1rem;margin:1rem 0 2rem; }}
.card,table {{ background:#182028;border:1px solid #2d3944; }}
.card {{ border-radius:.6rem;padding:1rem; }} .metric {{ font-size:2rem;font-weight:700; }}
table {{ width:100%;border-collapse:collapse; }} th,td {{ text-align:left;padding:.65rem;border-bottom:1px solid #2d3944; }}
th,.muted {{ color:#a8b5c2; }} .warning {{ padding:1rem;border:1px solid #8a6f2a;background:#2a2416;border-radius:.6rem; }}
</style></head><body><header><h1>NNTPIntel</h1><nav><a href="/">Dashboard</a><a href="/web/servers">Servers</a><a href="/web/groups">Groups</a><a href="/web/events">Events</a><a href="/web/propagation">Propagation</a></nav></header><main>
<p><a href="/web/propagation">← Propagation</a> · <a href="/web/propagation/topology/history">Topology history / stability</a> · <a href="/web/propagation/topology/anomalies">Topology anomalies</a> · <a href="/web/propagation/topology/incidents">Topology incidents</a> · <a href="/web/propagation/topology/impact">Impact / centrality</a></p><h2>Inferred propagation topology</h2>
<div class="warning"><strong>Inference only.</strong> {escape(str(topology["disclaimer"]))}</div>
<div class="cards">
<div class="card"><div class="muted">Nodes</div><div class="metric">{topology["node_count"]}</div></div>
<div class="card"><div class="muted">Inferred edges</div><div class="metric">{topology["edge_count"]}</div></div>
<div class="card"><div class="muted">Comparable articles</div><div class="metric">{topology["comparable_article_count"]}</div></div>
<div class="card"><div class="muted">Min confidence</div><div class="metric">{topology["min_confidence"]}</div></div>
</div>
<section><h2>Observed precedence edges</h2><table><thead><tr><th>Earlier server</th><th></th><th>Later server</th><th>Directional samples</th><th>Forward / reverse / ties</th><th>Confidence</th><th>Median lead s</th></tr></thead><tbody>{edge_rows}</tbody></table></section>
<section><h2>Servers</h2><table><thead><tr><th>ID</th><th>Host</th></tr></thead><tbody>{node_rows}</tbody></table></section>
</main></body></html>"""
