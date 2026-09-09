from __future__ import annotations

from html import escape

from nntpintel.propagation_topology_explain import explain_topology_ref
from nntpintel.storage import Storage


def _rows(values: list[tuple[str, object]]) -> str:
    return "".join(
        f"<tr><th>{escape(label)}</th><td>{escape(str(value))}</td></tr>"
        for label, value in values
    )


def explain_page(storage: Storage, evidence_ref: str) -> str | None:
    data = explain_topology_ref(storage, evidence_ref)
    if data is None:
        return None
    limitations = "".join(f"<li>{escape(str(item))}</li>" for item in data["limitations"])
    kind = data["conclusion_type"]
    if kind == "server":
        quality = data["quality"] or {}
        risk = data["risk"] or {}
        details = "<table><tbody>" + _rows([
            ("Server", data["host"]),
            ("Risk", f'{risk.get("risk_score", "")} {risk.get("risk_level", "")}'),
            ("Evidence level", risk.get("evidence_level", "")),
            ("Coverage", quality.get("valid_presence_coverage", "")),
            ("Freshness", quality.get("freshness", "")),
            ("Campaigns", data["evidence"]["campaign_ids"]),
            ("Message-IDs", data["evidence"]["message_ids"]),
            ("Observation IDs", data["evidence"]["valid_presence_observation_ids"]),
        ]) + "</tbody></table>"
    elif kind == "edge":
        details = "<table><tbody>" + _rows([
            ("Observed precedence", f'{data["source_host"]} → {data["target_host"]}'),
            ("Confidence", data["edge_confidence"]),
            ("Directional samples", data["directional_sample_count"]),
            ("Supporting articles", data["evidence"]["supporting_article_count"]),
        ]) + "</tbody></table>"
    elif kind == "risk_server":
        item = data["risk"]
        details = "<table><tbody>" + _rows([
            ("Server", data["host"]),
            ("Risk", f'{item["risk_score"]} {item["risk_level"]}'),
            ("Evidence", item["evidence_level"]),
            ("Incident input", item["incident_score"]),
            ("Resilience input", item["resilience_score"]),
            ("Impact input", item["impact_score"]),
            ("Gateway input", item["gateway_score"]),
        ]) + "</tbody></table>"
    elif kind == "incident":
        item = data["incident"]
        details = "<table><tbody>" + _rows([
            ("Incident", item["id"]),
            ("Server", item["host"]),
            ("Type", item["kind"]),
            ("Severity", item["severity"]),
            ("Status", item["status"]),
            ("Triage priority", item["triage_priority_score"]),
            ("Evidence", item["evidence_level"]),
            ("Impact", item["impact_score"]),
        ]) + "</tbody></table>"
    else:
        item = data["community"]
        details = "<table><tbody>" + _rows([
            ("Community", item["community_id"]),
            ("Risk", f'{item["risk_score"]} {item["risk_level"]}'),
            ("Evidence", item["evidence_level"]),
            ("Servers", item["server_count"]),
            ("Open incidents", item["open_incident_count"]),
            ("Gateways", item["gateway_server_count"]),
            ("Members", item["members"]),
        ]) + "</tbody></table>"
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Topology explain - NNTPIntel</title><style>:root{{color-scheme:dark;font-family:system-ui,sans-serif}}body{{margin:0;background:#101418;color:#e8edf2}}header{{padding:1.5rem 2rem;background:#182028;border-bottom:1px solid #2d3944}}main{{padding:1.5rem 2rem 3rem;max-width:1300px;margin:auto}}a{{color:#9fd3ff}}table{{width:100%;border-collapse:collapse;background:#182028;border:1px solid #2d3944;margin:1rem 0 2rem}}th,td{{text-align:left;padding:.65rem;border-bottom:1px solid #2d3944}}th{{color:#a8b5c2}}.warning{{border:1px solid #8a6d1d;background:#2a2412;padding:1rem;border-radius:.5rem}}</style></head><body><header><h1>NNTPIntel</h1></header><main><p><a href="/web/propagation/topology/evidence">← Evidence provenance</a></p><h2>Why does NNTPIntel believe this?</h2><p><code>{escape(evidence_ref)}</code></p><p class="warning"><strong>Inference only.</strong> {escape(str(data["why"]))}</p>{details}<h3>Limitations</h3><ul>{limitations}</ul></main></body></html>"""
