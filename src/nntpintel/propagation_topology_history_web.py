from __future__ import annotations

from html import escape

from nntpintel.propagation_topology_history import topology_history
from nntpintel.storage import Storage


def history_page(storage: Storage) -> str:
    data = topology_history(storage)
    edge_rows = "".join(
        "<tr>"
        f'<td>{escape(str(item["source_host"]))} → {escape(str(item["target_host"]))}</td>'
        f'<td>{item["observed_days"]}/{data["days"]}</td>'
        f'<td>{item["stability_percent"]}</td>'
        f'<td>{item["median_confidence"]}</td>'
        f'<td>{"yes" if item["latest_present"] else "no"}</td>'
        "</tr>"
        for item in data["edges"]
    ) or '<tr><td colspan="5">No stable inferred edges yet.</td></tr>'
    event_rows = "".join(
        "<tr>"
        f'<td>{escape(str(item["at"]))}</td>'
        f'<td>{escape(str(item["event"]))}</td>'
        f'<td>{escape(str(item["source_host"]))} → {escape(str(item["target_host"]))}</td>'
        f'<td>{item["confidence"]}</td>'
        f'<td>{item["median_lead_seconds"]}</td>'
        "</tr>"
        for item in data["events"][-100:]
    ) or '<tr><td colspan="5">No topology-change events yet.</td></tr>'
    daily_rows = "".join(
        "<tr>"
        f'<td>{escape(str(item["start"]))}</td>'
        f'<td>{item["article_count"]}</td>'
        f'<td>{item["edge_count"]}</td>'
        "</tr>"
        for item in data["snapshots"]
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Topology history - NNTPIntel</title>
<style>
:root{{color-scheme:dark;font-family:system-ui,sans-serif}}body{{margin:0;background:#101418;color:#e8edf2}}
header{{padding:1.5rem 2rem;background:#182028;border-bottom:1px solid #2d3944}}main{{padding:1.5rem 2rem 3rem;max-width:1400px;margin:auto}}
a{{color:#9fd3ff}}table{{width:100%;border-collapse:collapse;background:#182028;border:1px solid #2d3944;margin-bottom:2rem}}
th,td{{text-align:left;padding:.65rem;border-bottom:1px solid #2d3944}}th,.muted{{color:#a8b5c2}}.warning{{border:1px solid #8a6d1d;background:#2a2412;padding:1rem;border-radius:.5rem}}
</style></head><body><header><h1>NNTPIntel</h1></header><main>
<p><a href="/web/propagation/topology">← Inferred topology</a></p>
<h2>Topology history / stability</h2>
<p class="warning"><strong>Inference only.</strong> {escape(data["disclaimer"])}</p>
<p>Window: {data["days"]} days · minimum samples: {data["min_samples"]} · minimum confidence: {data["min_confidence"]}</p>
<h3>Edge stability</h3><table><thead><tr><th>Observed precedence</th><th>Days present</th><th>Stability %</th><th>Median confidence</th><th>Present latest</th></tr></thead><tbody>{edge_rows}</tbody></table>
<h3>Topology-change events</h3><table><thead><tr><th>At</th><th>Event</th><th>Edge</th><th>Confidence</th><th>Median lead s</th></tr></thead><tbody>{event_rows}</tbody></table>
<h3>Daily snapshots</h3><table><thead><tr><th>Day</th><th>Targeted articles</th><th>Edges</th></tr></thead><tbody>{daily_rows}</tbody></table>
</main></body></html>"""
