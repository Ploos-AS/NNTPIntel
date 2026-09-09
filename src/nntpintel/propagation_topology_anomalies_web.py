from __future__ import annotations

from html import escape

from nntpintel.propagation_topology_anomalies import topology_anomalies
from nntpintel.storage import Storage


def anomalies_page(storage: Storage) -> str:
    data = topology_anomalies(storage)
    rows = "".join(
        "<tr>"
        f'<td>{escape(str(item["at"]))}</td>'
        f'<td>{escape(str(item["kind"]))}</td>'
        f'<td>{escape(str(item["severity"]))}</td>'
        f'<td>{escape(str(item.get("source_host", "")))}</td>'
        f'<td>{escape(str(item.get("target_host", "")))}</td>'
        f'<td>{escape(str(item.get("confidence_drop", item.get("event_count", ""))))}</td>'
        "</tr>"
        for item in data["anomalies"][-100:]
    ) or '<tr><td colspan="6">No topology anomalies detected.</td></tr>'
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Topology anomalies - NNTPIntel</title>
<style>
:root{{color-scheme:dark;font-family:system-ui,sans-serif}}body{{margin:0;background:#101418;color:#e8edf2}}
header{{padding:1.5rem 2rem;background:#182028;border-bottom:1px solid #2d3944}}main{{padding:1.5rem 2rem 3rem;max-width:1400px;margin:auto}}
a{{color:#9fd3ff}}.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:1rem;margin:1rem 0 2rem}}
.card,table{{background:#182028;border:1px solid #2d3944}}.card{{padding:1rem;border-radius:.6rem}}.metric{{font-size:2rem;font-weight:700}}
table{{width:100%;border-collapse:collapse}}th,td{{text-align:left;padding:.65rem;border-bottom:1px solid #2d3944}}th,.muted{{color:#a8b5c2}}
.warning{{border:1px solid #8a6d1d;background:#2a2412;padding:1rem;border-radius:.5rem}}
</style></head><body><header><h1>NNTPIntel</h1></header><main>
<p><a href="/web/propagation/topology">← Inferred topology</a></p>
<h2>Topology anomalies</h2>
<p class="warning"><strong>Inference only.</strong> {escape(data["disclaimer"])}</p>
<div class="cards">
<div class="card"><div class="muted">Anomalies</div><div class="metric">{data["anomaly_count"]}</div></div>
<div class="card"><div class="muted">Reversals</div><div class="metric">{data["counts"]["edge_reversal"]}</div></div>
<div class="card"><div class="muted">Confidence collapses</div><div class="metric">{data["counts"]["confidence_collapse"]}</div></div>
<div class="card"><div class="muted">Churn events</div><div class="metric">{data["counts"]["topology_churn"]}</div></div>
</div>
<p>Window: {data["days"]} days · confidence-drop threshold: {data["min_confidence_drop"]} · churn threshold: {data["min_churn_events"]}</p>
<table><thead><tr><th>At</th><th>Kind</th><th>Severity</th><th>Source</th><th>Target</th><th>Delta/count</th></tr></thead><tbody>{rows}</tbody></table>
</main></body></html>"""
