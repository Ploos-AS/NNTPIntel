from __future__ import annotations

from html import escape

from nntpintel.propagation_topology_impact import topology_impact
from nntpintel.storage import Storage


def impact_page(storage: Storage) -> str:
    data = topology_impact(storage)
    node_rows = "".join(
        "<tr>"
        f'<td>{escape(str(item["host"]))}</td>'
        f'<td>{item["impact_score"]}</td>'
        f'<td>{item["degree"]}</td>'
        f'<td>{item["out_degree"]}</td>'
        f'<td>{item["in_degree"]}</td>'
        f'<td>{item["weighted_confidence"]}</td>'
        f'<td>{item["bridge_score"]}</td>'
        "</tr>"
        for item in data["nodes"]
    ) or '<tr><td colspan="7">No inferred topology nodes yet.</td></tr>'
    edge_rows = "".join(
        "<tr>"
        f'<td>{escape(str(item["source_host"]))}</td><td>→</td>'
        f'<td>{escape(str(item["target_host"]))}</td>'
        f'<td>{item["impact_score"]}</td><td>{item["confidence"]}</td>'
        "</tr>"
        for item in data["edges"]
    ) or '<tr><td colspan="5">No inferred topology edges yet.</td></tr>'
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Topology impact - NNTPIntel</title><style>
:root{{color-scheme:dark;font-family:system-ui,sans-serif}}body{{margin:0;background:#101418;color:#e8edf2}}
header{{padding:1.5rem 2rem;background:#182028;border-bottom:1px solid #2d3944}}main{{padding:1.5rem 2rem 3rem;max-width:1400px;margin:auto}}
a{{color:#9fd3ff}}table{{width:100%;border-collapse:collapse;background:#182028;border:1px solid #2d3944;margin-bottom:2rem}}
th,td{{text-align:left;padding:.65rem;border-bottom:1px solid #2d3944}}th{{color:#a8b5c2}}.warning{{border:1px solid #8a6d1d;background:#2a2412;padding:1rem;border-radius:.5rem}}
</style></head><body><header><h1>NNTPIntel</h1></header><main>
<p><a href="/web/propagation/topology">← Inferred topology</a></p><h2>Topology impact / centrality</h2>
<p class="warning"><strong>Inference only.</strong> {escape(data["disclaimer"])}</p>
<h3>Server impact ranking</h3><table><thead><tr><th>Server</th><th>Impact</th><th>Degree</th><th>Out</th><th>In</th><th>Weighted confidence</th><th>Bridge</th></tr></thead><tbody>{node_rows}</tbody></table>
<h3>Edge impact ranking</h3><table><thead><tr><th>Source</th><th></th><th>Target</th><th>Impact</th><th>Confidence</th></tr></thead><tbody>{edge_rows}</tbody></table>
</main></body></html>"""
