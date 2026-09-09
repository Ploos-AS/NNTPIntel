from __future__ import annotations

from html import escape

from nntpintel.propagation_topology_explain import explain_topology_ref
from nntpintel.storage import Storage


def explain_page(storage: Storage, evidence_ref: str) -> str | None:
    data = explain_topology_ref(storage, evidence_ref)
    if data is None:
        return None
    limitations = "".join(f"<li>{escape(str(item))}</li>" for item in data["limitations"])
    if data["conclusion_type"] == "server":
        quality = data["quality"] or {}
        risk = data["risk"] or {}
        details = f"""
        <table><tbody>
        <tr><th>Server</th><td>{escape(str(data["host"]))}</td></tr>
        <tr><th>Risk</th><td>{risk.get("risk_score", "")} {escape(str(risk.get("risk_level", "")))}</td></tr>
        <tr><th>Evidence level</th><td>{escape(str(risk.get("evidence_level", "")))}</td></tr>
        <tr><th>Coverage</th><td>{quality.get("valid_presence_coverage", "")}</td></tr>
        <tr><th>Freshness</th><td>{escape(str(quality.get("freshness", "")))}</td></tr>
        <tr><th>Campaigns</th><td>{escape(str(data["evidence"]["campaign_ids"]))}</td></tr>
        <tr><th>Message-IDs</th><td>{escape(str(data["evidence"]["message_ids"]))}</td></tr>
        <tr><th>Observation IDs</th><td>{escape(str(data["evidence"]["valid_presence_observation_ids"]))}</td></tr>
        </tbody></table>"""
    else:
        details = f"""
        <table><tbody>
        <tr><th>Observed precedence</th><td>{escape(str(data["source_host"]))} → {escape(str(data["target_host"]))}</td></tr>
        <tr><th>Confidence</th><td>{data["edge_confidence"]}</td></tr>
        <tr><th>Directional samples</th><td>{data["directional_sample_count"]}</td></tr>
        <tr><th>Supporting articles</th><td>{data["evidence"]["supporting_article_count"]}</td></tr>
        </tbody></table>"""
        details += "<h3>Supporting observations</h3><table><thead><tr><th>Message-ID</th><th>Source obs</th><th>Target obs</th><th>Source first seen</th><th>Target first seen</th></tr></thead><tbody>"
        details += "".join(
            "<tr>"
            f'<td>{escape(str(item["message_id"] or ""))}</td>'
            f'<td>{item["source_observation_id"]}</td>'
            f'<td>{item["target_observation_id"]}</td>'
            f'<td>{escape(str(item["source_first_seen_at"]))}</td>'
            f'<td>{escape(str(item["target_first_seen_at"]))}</td>'
            "</tr>"
            for item in data["evidence"]["supporting_articles"]
        )
        details += "</tbody></table>"
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Topology explain - NNTPIntel</title><style>:root{{color-scheme:dark;font-family:system-ui,sans-serif}}body{{margin:0;background:#101418;color:#e8edf2}}header{{padding:1.5rem 2rem;background:#182028;border-bottom:1px solid #2d3944}}main{{padding:1.5rem 2rem 3rem;max-width:1300px;margin:auto}}a{{color:#9fd3ff}}table{{width:100%;border-collapse:collapse;background:#182028;border:1px solid #2d3944;margin:1rem 0 2rem}}th,td{{text-align:left;padding:.65rem;border-bottom:1px solid #2d3944}}th{{color:#a8b5c2}}.warning{{border:1px solid #8a6d1d;background:#2a2412;padding:1rem;border-radius:.5rem}}</style></head><body><header><h1>NNTPIntel</h1></header><main><p><a href="/web/propagation/topology/evidence">← Evidence provenance</a></p><h2>Why does NNTPIntel believe this?</h2><p><code>{escape(evidence_ref)}</code></p><p class="warning"><strong>Inference only.</strong> {escape(str(data["why"]))}</p>{details}<h3>Limitations</h3><ul>{limitations}</ul></main></body></html>"""
