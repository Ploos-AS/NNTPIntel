from __future__ import annotations

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from nntpintel.candidate_observability import list_candidate_observability
from nntpintel.candidates import list_candidate_qualifications
from nntpintel.cycle import list_cycle_runs
from nntpintel.propagation_analytics import propagation_analytics
from nntpintel.propagation_incidents import list_propagation_incidents
from nntpintel.propagation_topology import inferred_propagation_topology
from nntpintel.propagation_topology_anomalies import topology_anomalies
from nntpintel.propagation_topology_history import topology_history
from nntpintel.propagation_trends import propagation_trends
from nntpintel.propagation_view import (
    get_propagation_article,
    list_propagation_articles,
    list_propagation_campaigns,
)
from nntpintel.source_management import list_source_management
from nntpintel.storage import Storage


def _rows(storage: Storage, query: str, params: tuple = ()) -> list[dict]:
    with storage.connect() as conn:
        return [dict(row) for row in conn.execute(query, params).fetchall()]


def list_servers(storage: Storage) -> list[dict]:
    return _rows(storage, """
        SELECT s.id, s.host, s.enabled, s.created_at, COUNT(e.id) AS endpoint_count
        FROM servers s LEFT JOIN endpoints e ON e.server_id = s.id
        GROUP BY s.id ORDER BY s.host
    """)


def list_endpoints(storage: Storage) -> list[dict]:
    return _rows(storage, """
        SELECT e.*, s.host FROM endpoints e JOIN servers s ON s.id = e.server_id
        ORDER BY s.host, e.port
    """)


def list_groups(storage: Storage) -> list[dict]:
    return _rows(storage, """
        SELECT n.id, n.name, h.name AS hierarchy, n.first_seen_at, n.last_seen_at,
               (SELECT gs.high_water FROM group_snapshots gs WHERE gs.newsgroup_id=n.id ORDER BY gs.observed_at DESC, gs.id DESC LIMIT 1) AS high_water,
               (SELECT gs.low_water FROM group_snapshots gs WHERE gs.newsgroup_id=n.id ORDER BY gs.observed_at DESC, gs.id DESC LIMIT 1) AS low_water,
               (SELECT gs.posting_status FROM group_snapshots gs WHERE gs.newsgroup_id=n.id ORDER BY gs.observed_at DESC, gs.id DESC LIMIT 1) AS posting_status,
               (SELECT gs.description FROM group_snapshots gs WHERE gs.newsgroup_id=n.id ORDER BY gs.observed_at DESC, gs.id DESC LIMIT 1) AS description
        FROM newsgroups n JOIN hierarchies h ON h.id=n.hierarchy_id ORDER BY n.name
    """)


def list_hierarchies(storage: Storage) -> list[dict]:
    return _rows(storage, """
        SELECT h.id,h.name,h.first_seen_at,h.last_seen_at,COUNT(n.id) AS group_count
        FROM hierarchies h LEFT JOIN newsgroups n ON n.hierarchy_id=h.id
        GROUP BY h.id ORDER BY h.name
    """)


def list_events(storage: Storage, *, limit: int = 100) -> list[dict]:
    return _rows(storage, """
        SELECT ge.id,ge.endpoint_id,s.host,e.port,n.name AS newsgroup,ge.observed_at,ge.event_type,ge.detail_json
        FROM group_events ge JOIN endpoints e ON e.id=ge.endpoint_id JOIN servers s ON s.id=e.server_id JOIN newsgroups n ON n.id=ge.newsgroup_id
        ORDER BY ge.observed_at DESC, ge.id DESC LIMIT ?
    """, (limit,))


def list_server_observations(storage: Storage, server_id: int, *, limit: int = 100) -> list[dict]:
    rows = _rows(storage, """
        SELECT o.id,o.endpoint_id,e.port,e.transport,e.starttls,o.observed_at,o.success,o.connect_ms,o.greeting_code,
               o.greeting,o.posting_allowed,o.mode_reader_code,o.mode_reader_response,o.capabilities_json,o.tls_json,o.error
        FROM observations o JOIN endpoints e ON e.id=o.endpoint_id
        WHERE e.server_id=? ORDER BY o.observed_at DESC,o.id DESC LIMIT ?
    """, (server_id, limit))
    for row in rows:
        row["capabilities"] = json.loads(row.pop("capabilities_json"))
        row["tls"] = json.loads(row.pop("tls_json"))
    return rows


def list_server_events(storage: Storage, server_id: int, *, limit: int = 100) -> list[dict]:
    return _rows(storage, """
        SELECT ge.id,ge.endpoint_id,e.port,n.name AS newsgroup,ge.observed_at,ge.event_type,ge.detail_json
        FROM group_events ge JOIN endpoints e ON e.id=ge.endpoint_id JOIN newsgroups n ON n.id=ge.newsgroup_id
        WHERE e.server_id=? ORDER BY ge.observed_at DESC,ge.id DESC LIMIT ?
    """, (server_id, limit))


def server_availability(observations: list[dict]) -> dict:
    ordered = list(reversed(observations))
    total = len(ordered)
    successes = sum(1 for item in ordered if item["success"])
    failures = total - successes
    latencies = [float(item["connect_ms"]) for item in ordered if item["connect_ms"] is not None]
    transitions: list[dict] = []
    previous: bool | None = None
    for item in ordered:
        current = bool(item["success"])
        if previous is not None and current != previous:
            transitions.append({"observed_at": item["observed_at"], "endpoint_id": item["endpoint_id"], "port": item["port"], "event": "recovered" if current else "failed"})
        previous = current
    latency_series = [{"observed_at": item["observed_at"], "endpoint_id": item["endpoint_id"], "port": item["port"], "connect_ms": item["connect_ms"]} for item in ordered if item["connect_ms"] is not None]
    return {
        "sample_count": total, "success_count": successes, "failure_count": failures,
        "availability_percent": round((successes / total) * 100, 2) if total else None,
        "average_latency_ms": round(sum(latencies) / len(latencies), 2) if latencies else None,
        "min_latency_ms": min(latencies) if latencies else None,
        "max_latency_ms": max(latencies) if latencies else None,
        "transitions": transitions, "latency_series": latency_series,
    }


def get_server(storage: Storage, server_id: int) -> dict | None:
    rows = _rows(storage, "SELECT id,host,enabled,created_at FROM servers WHERE id=?", (server_id,))
    if not rows:
        return None
    server = rows[0]
    server["endpoints"] = _rows(storage, "SELECT * FROM endpoints WHERE server_id=? ORDER BY port", (server_id,))
    server["observations"] = list_server_observations(storage, server_id, limit=100)
    server["events"] = list_server_events(storage, server_id, limit=100)
    server["availability"] = server_availability(server["observations"])
    return server


class APIHandler(BaseHTTPRequestHandler):
    storage: Storage

    def _send_json(self, payload: object, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, sort_keys=True).encode("utf-8")
        self.send_response(status); self.send_header("Content-Type", "application/json; charset=utf-8"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)

    def _send_html(self, html: str, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = html.encode("utf-8")
        self.send_response(status); self.send_header("Content-Type", "text/html; charset=utf-8"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path in {"/", "/web"}:
            from nntpintel.web import dashboard
            self._send_html(dashboard(self.storage)); return
        if path == "/web/servers":
            from nntpintel.web import servers_page
            self._send_html(servers_page(self.storage)); return
        if path == "/web/sources":
            from nntpintel.source_web import sources_page
            self._send_html(sources_page(self.storage)); return
        if path == "/web/candidates":
            from nntpintel.candidate_web import candidates_page
            self._send_html(candidates_page(self.storage)); return
        if path == "/web/cycles":
            from nntpintel.cycle_web import cycle_runs_page
            self._send_html(cycle_runs_page(self.storage)); return
        if path == "/web/propagation":
            from nntpintel.propagation_web import propagation_page
            self._send_html(propagation_page(self.storage)); return
        if path == "/web/propagation/trends":
            from nntpintel.propagation_trends_web import trends_page
            self._send_html(trends_page(self.storage)); return
        if path == "/web/propagation/incidents":
            from nntpintel.propagation_incidents_web import incidents_page
            self._send_html(incidents_page(self.storage)); return
        if path == "/web/propagation/topology":
            from nntpintel.propagation_topology_web import topology_page
            self._send_html(topology_page(self.storage)); return
        if path == "/web/propagation/topology/history":
            from nntpintel.propagation_topology_history_web import history_page
            self._send_html(history_page(self.storage)); return
        if path == "/web/propagation/topology/anomalies":
            from nntpintel.propagation_topology_anomalies_web import anomalies_page
            self._send_html(anomalies_page(self.storage)); return
        if path.startswith("/web/propagation/"):
            from nntpintel.propagation_web import propagation_detail_page
            try: article_id = int(path.rsplit("/", 1)[1])
            except ValueError: self._send_html("<h1>Not found</h1>", HTTPStatus.NOT_FOUND); return
            html = propagation_detail_page(self.storage, article_id)
            self._send_html(html if html is not None else "<h1>Not found</h1>", HTTPStatus.OK if html is not None else HTTPStatus.NOT_FOUND); return
        if path.startswith("/web/servers/"):
            from nntpintel.web import server_detail_page
            try: server_id = int(path.rsplit("/", 1)[1])
            except ValueError: self._send_html("<h1>Not found</h1>", HTTPStatus.NOT_FOUND); return
            html = server_detail_page(self.storage, server_id)
            self._send_html(html if html is not None else "<h1>Not found</h1>", HTTPStatus.OK if html is not None else HTTPStatus.NOT_FOUND); return
        if path == "/web/groups":
            from nntpintel.web import groups_page
            self._send_html(groups_page(self.storage)); return
        if path == "/web/events":
            from nntpintel.web import events_page
            self._send_html(events_page(self.storage)); return
        if path == "/healthz": self._send_json({"status": "ok"}); return
        if path == "/servers": self._send_json(list_servers(self.storage)); return
        if path == "/endpoints": self._send_json(list_endpoints(self.storage)); return
        if path == "/groups": self._send_json(list_groups(self.storage)); return
        if path == "/hierarchies": self._send_json(list_hierarchies(self.storage)); return
        if path == "/events": self._send_json(list_events(self.storage)); return
        if path == "/sources": self._send_json(list_source_management(self.storage)); return
        if path == "/candidates": self._send_json(list_candidate_observability(self.storage)); return
        if path == "/candidate-qualifications": self._send_json(list_candidate_qualifications(self.storage)); return
        if path == "/cycle-runs": self._send_json(list_cycle_runs(self.storage)); return
        if path == "/propagation/analytics": self._send_json(propagation_analytics(self.storage)); return
        if path == "/propagation/trends": self._send_json(propagation_trends(self.storage)); return
        if path == "/propagation/incidents": self._send_json(list_propagation_incidents(self.storage)); return
        if path == "/propagation/topology": self._send_json(inferred_propagation_topology(self.storage)); return
        if path == "/propagation/topology/history": self._send_json(topology_history(self.storage)); return
        if path == "/propagation/topology/anomalies": self._send_json(topology_anomalies(self.storage)); return
        if path == "/propagation/articles": self._send_json(list_propagation_articles(self.storage)); return
        if path == "/propagation/campaigns": self._send_json(list_propagation_campaigns(self.storage)); return
        if path.startswith("/propagation/articles/"):
            try: article_id = int(path.rsplit("/", 1)[1])
            except ValueError: self._send_json({"error": "not found"}, HTTPStatus.NOT_FOUND); return
            article = get_propagation_article(self.storage, article_id)
            self._send_json(article if article is not None else {"error": "not found"}, HTTPStatus.OK if article is not None else HTTPStatus.NOT_FOUND); return
        if path.startswith("/servers/"):
            try: server_id = int(path.rsplit("/", 1)[1])
            except ValueError: self._send_json({"error": "not found"}, HTTPStatus.NOT_FOUND); return
            server = get_server(self.storage, server_id)
            self._send_json(server if server is not None else {"error": "not found"}, HTTPStatus.OK if server is not None else HTTPStatus.NOT_FOUND); return
        self._send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)

    def log_message(self, format: str, *args: object) -> None:
        return


def make_server(storage: Storage, host: str = "127.0.0.1", port: int = 8080) -> ThreadingHTTPServer:
    handler = type("NNTPIntelAPIHandler", (APIHandler,), {"storage": storage})
    return ThreadingHTTPServer((host, port), handler)


def serve(storage: Storage, *, host: str = "127.0.0.1", port: int = 8080) -> None:
    server = make_server(storage, host, port)
    try: server.serve_forever()
    finally: server.server_close()
