from __future__ import annotations

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from nntpintel.storage import Storage


def _rows(storage: Storage, query: str, params: tuple = ()) -> list[dict]:
    with storage.connect() as conn:
        return [dict(row) for row in conn.execute(query, params).fetchall()]


def list_servers(storage: Storage) -> list[dict]:
    return _rows(
        storage,
        """
        SELECT s.id, s.host, s.enabled, s.created_at,
               COUNT(e.id) AS endpoint_count
        FROM servers s
        LEFT JOIN endpoints e ON e.server_id = s.id
        GROUP BY s.id
        ORDER BY s.host
        """,
    )


def list_endpoints(storage: Storage) -> list[dict]:
    return _rows(
        storage,
        """
        SELECT e.*, s.host
        FROM endpoints e
        JOIN servers s ON s.id = e.server_id
        ORDER BY s.host, e.port
        """,
    )


def list_groups(storage: Storage) -> list[dict]:
    return _rows(
        storage,
        """
        SELECT n.id, n.name, h.name AS hierarchy,
               n.first_seen_at, n.last_seen_at,
               (
                   SELECT gs.high_water
                   FROM group_snapshots gs
                   WHERE gs.newsgroup_id = n.id
                   ORDER BY gs.observed_at DESC, gs.id DESC
                   LIMIT 1
               ) AS high_water,
               (
                   SELECT gs.low_water
                   FROM group_snapshots gs
                   WHERE gs.newsgroup_id = n.id
                   ORDER BY gs.observed_at DESC, gs.id DESC
                   LIMIT 1
               ) AS low_water,
               (
                   SELECT gs.posting_status
                   FROM group_snapshots gs
                   WHERE gs.newsgroup_id = n.id
                   ORDER BY gs.observed_at DESC, gs.id DESC
                   LIMIT 1
               ) AS posting_status,
               (
                   SELECT gs.description
                   FROM group_snapshots gs
                   WHERE gs.newsgroup_id = n.id
                   ORDER BY gs.observed_at DESC, gs.id DESC
                   LIMIT 1
               ) AS description
        FROM newsgroups n
        JOIN hierarchies h ON h.id = n.hierarchy_id
        ORDER BY n.name
        """,
    )


def list_hierarchies(storage: Storage) -> list[dict]:
    return _rows(
        storage,
        """
        SELECT h.id, h.name, h.first_seen_at, h.last_seen_at,
               COUNT(n.id) AS group_count
        FROM hierarchies h
        LEFT JOIN newsgroups n ON n.hierarchy_id = h.id
        GROUP BY h.id
        ORDER BY h.name
        """,
    )


def list_events(storage: Storage, *, limit: int = 100) -> list[dict]:
    return _rows(
        storage,
        """
        SELECT ge.id, ge.endpoint_id, s.host, e.port,
               n.name AS newsgroup, ge.observed_at,
               ge.event_type, ge.detail_json
        FROM group_events ge
        JOIN endpoints e ON e.id = ge.endpoint_id
        JOIN servers s ON s.id = e.server_id
        JOIN newsgroups n ON n.id = ge.newsgroup_id
        ORDER BY ge.observed_at DESC, ge.id DESC
        LIMIT ?
        """,
        (limit,),
    )


def get_server(storage: Storage, server_id: int) -> dict | None:
    rows = _rows(
        storage,
        "SELECT id, host, enabled, created_at FROM servers WHERE id = ?",
        (server_id,),
    )
    if not rows:
        return None
    server = rows[0]
    server["endpoints"] = _rows(
        storage,
        "SELECT * FROM endpoints WHERE server_id = ? ORDER BY port",
        (server_id,),
    )
    return server


class APIHandler(BaseHTTPRequestHandler):
    storage: Storage

    def _send_json(self, payload: object, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/healthz":
            self._send_json({"status": "ok"})
            return
        if path == "/servers":
            self._send_json(list_servers(self.storage))
            return
        if path == "/endpoints":
            self._send_json(list_endpoints(self.storage))
            return
        if path == "/groups":
            self._send_json(list_groups(self.storage))
            return
        if path == "/hierarchies":
            self._send_json(list_hierarchies(self.storage))
            return
        if path == "/events":
            self._send_json(list_events(self.storage))
            return
        if path.startswith("/servers/"):
            try:
                server_id = int(path.rsplit("/", 1)[1])
            except ValueError:
                self._send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)
                return
            server = get_server(self.storage, server_id)
            if server is None:
                self._send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)
            else:
                self._send_json(server)
            return
        self._send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)

    def log_message(self, format: str, *args: object) -> None:
        return


def make_server(storage: Storage, host: str = "127.0.0.1", port: int = 8080) -> ThreadingHTTPServer:
    handler = type("NNTPIntelAPIHandler", (APIHandler,), {"storage": storage})
    return ThreadingHTTPServer((host, port), handler)


def serve(storage: Storage, *, host: str = "127.0.0.1", port: int = 8080) -> None:
    server = make_server(storage, host, port)
    try:
        server.serve_forever()
    finally:
        server.server_close()
