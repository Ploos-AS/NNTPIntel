from __future__ import annotations

import argparse
import json
import os
import re
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

from nntpintel.group_history_web import group_history_page
from nntpintel.propagation_history_web import propagation_history_page
from nntpintel.protocol_history_web import protocol_history_page
from nntpintel.statistics import parse_statistics_time
from nntpintel.statistics_api import (
    group_statistics_request,
    propagation_statistics_request,
    protocol_statistics_request,
    server_statistics_request,
    topology_statistics_request,
)
from nntpintel.statistics_cache import StatisticsCache
from nntpintel.statistics_drilldown import server_observation_drilldown
from nntpintel.statistics_freshness import rollup_freshness_token
from nntpintel.statistics_web import (
    historical_statistics_page,
    resolve_web_range,
    server_history_page,
)
from nntpintel.storage_backend import StorageBackend, open_storage
from nntpintel.topology_history_web import topology_history_page

_ROUTES = {
    "/api/v1/statistics/servers": ("servers", server_statistics_request),
    "/api/v1/statistics/groups": ("groups", group_statistics_request),
    "/api/v1/statistics/protocol": ("protocol", protocol_statistics_request),
    "/api/v1/statistics/propagation": ("propagation", propagation_statistics_request),
    "/api/v1/statistics/topology": ("topology", topology_statistics_request),
}
_SERVER_HISTORY = re.compile(r"^/web/statistics/server/(\d+)$")
_SERVER_DRILLDOWN = re.compile(r"^/api/v1/statistics/server/(\d+)/observations$")
_GROUP_HISTORY = re.compile(r"^/web/statistics/server/(\d+)/groups$")
_PROTOCOL_HISTORY = re.compile(r"^/web/statistics/server/(\d+)/protocol$")
_PROPAGATION_HISTORY = re.compile(r"^/web/statistics/server/(\d+)/propagation$")


def _canonical_request(path: str, params: dict[str, list[str]]) -> str:
    pairs = sorted((key, value) for key, values in params.items() for value in values)
    query = urlencode(pairs)
    return f"{path}?{query}" if query else path


class StatisticsHTTPHandler(BaseHTTPRequestHandler):
    storage: StorageBackend
    statistics_cache: StatisticsCache

    def _send_json(
        self,
        payload: object,
        status: HTTPStatus = HTTPStatus.OK,
        *,
        cache_status: str | None = None,
    ) -> None:
        body = json.dumps(payload, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        if cache_status is not None:
            self.send_header("X-NNTPIntel-Cache", cache_status)
            self.send_header("Cache-Control", "public, max-age=30")
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, html: str, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        if parsed.path == "/healthz":
            self._send_json({"status": "ok", "backend": self.storage.backend_name})
            return

        drilldown_match = _SERVER_DRILLDOWN.fullmatch(parsed.path)
        if drilldown_match:
            try:
                start_text = params.get("start", [None])[0]
                end_text = params.get("end", [None])[0]
                if not start_text or not end_text:
                    raise ValueError("start and end are required for raw drill-down")
                limit_text = params.get("limit", ["100"])[0]
                payload = server_observation_drilldown(
                    self.storage,
                    server_id=int(drilldown_match.group(1)),
                    start=parse_statistics_time(start_text),
                    end=parse_statistics_time(end_text),
                    limit=int(limit_text),
                )
            except ValueError as exc:
                self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
                return
            except RuntimeError as exc:
                self._send_json({"error": str(exc)}, HTTPStatus.SERVICE_UNAVAILABLE)
                return
            self._send_json(payload)
            return

        if parsed.path == "/web/statistics/topology":
            resolution = params.get("resolution", ["day"])[0]
            preset = params.get("preset", ["30d"])[0]
            kind = params.get("kind", [None])[0] or None
            value = params.get("value", [None])[0] or None
            start_text = params.get("start", [None])[0] or None
            end_text = params.get("end", [None])[0] or None
            try:
                start, end, range_label = resolve_web_range(
                    resolution=resolution, preset=preset, start_text=start_text, end_text=end_text
                )
                html = topology_history_page(
                    self.storage, resolution=resolution,
                    preset=None if range_label == "custom" else preset,
                    start=start, end=end, range_label=range_label, kind=kind, value=value,
                )
            except ValueError as exc:
                self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST); return
            except RuntimeError as exc:
                self._send_json({"error": str(exc)}, HTTPStatus.SERVICE_UNAVAILABLE); return
            self._send_html(html); return

        propagation_match = _PROPAGATION_HISTORY.fullmatch(parsed.path)
        if propagation_match:
            resolution = params.get("resolution", ["day"])[0]; preset = params.get("preset", ["30d"])[0]
            kind = params.get("kind", [None])[0] or None; value = params.get("value", [None])[0] or None
            start_text = params.get("start", [None])[0] or None; end_text = params.get("end", [None])[0] or None
            try:
                start, end, range_label = resolve_web_range(resolution=resolution, preset=preset, start_text=start_text, end_text=end_text)
                html = propagation_history_page(
                    self.storage, int(propagation_match.group(1)), resolution=resolution,
                    preset=None if range_label == "custom" else preset, start=start, end=end,
                    range_label=range_label, kind=kind, value=value,
                )
            except ValueError as exc:
                self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST); return
            except RuntimeError as exc:
                self._send_json({"error": str(exc)}, HTTPStatus.SERVICE_UNAVAILABLE); return
            self._send_html(html); return

        protocol_match = _PROTOCOL_HISTORY.fullmatch(parsed.path)
        if protocol_match:
            resolution = params.get("resolution", ["day"])[0]; preset = params.get("preset", ["30d"])[0]
            kind = params.get("kind", [None])[0] or None; value = params.get("value", [None])[0] or None
            start_text = params.get("start", [None])[0] or None; end_text = params.get("end", [None])[0] or None
            try:
                start, end, range_label = resolve_web_range(resolution=resolution, preset=preset, start_text=start_text, end_text=end_text)
                html = protocol_history_page(
                    self.storage, int(protocol_match.group(1)), resolution=resolution,
                    preset=None if range_label == "custom" else preset, start=start, end=end,
                    range_label=range_label, kind=kind, value=value,
                )
            except ValueError as exc:
                self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST); return
            except RuntimeError as exc:
                self._send_json({"error": str(exc)}, HTTPStatus.SERVICE_UNAVAILABLE); return
            self._send_html(html); return

        group_match = _GROUP_HISTORY.fullmatch(parsed.path)
        if group_match:
            resolution = params.get("resolution", ["day"])[0]; preset = params.get("preset", ["30d"])[0]
            kind = params.get("kind", [None])[0] or None; value = params.get("value", [None])[0] or None
            start_text = params.get("start", [None])[0] or None; end_text = params.get("end", [None])[0] or None
            try:
                start, end, range_label = resolve_web_range(resolution=resolution, preset=preset, start_text=start_text, end_text=end_text)
                html = group_history_page(
                    self.storage, int(group_match.group(1)), resolution=resolution,
                    preset=None if range_label == "custom" else preset, start=start, end=end,
                    range_label=range_label, kind=kind, value=value,
                )
            except ValueError as exc:
                self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST); return
            except RuntimeError as exc:
                self._send_json({"error": str(exc)}, HTTPStatus.SERVICE_UNAVAILABLE); return
            self._send_html(html); return

        server_match = _SERVER_HISTORY.fullmatch(parsed.path)
        if server_match:
            resolution = params.get("resolution", ["hour"])[0]
            preset = params.get("preset", ["7d"])[0]
            start_text = params.get("start", [None])[0] or None
            end_text = params.get("end", [None])[0] or None
            try:
                start, end, range_label = resolve_web_range(
                    resolution=resolution, preset=preset, start_text=start_text, end_text=end_text
                )
                html = server_history_page(
                    self.storage, int(server_match.group(1)), resolution=resolution,
                    preset=None if range_label == "custom" else preset,
                    start=start, end=end, range_label=range_label,
                )
            except ValueError as exc:
                self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST); return
            except RuntimeError as exc:
                self._send_json({"error": str(exc)}, HTTPStatus.SERVICE_UNAVAILABLE); return
            self._send_html(html); return

        if parsed.path == "/web/statistics":
            resolution = params.get("resolution", ["day"])[0]
            preset = params.get("preset", [None])[0]
            start_text = params.get("start", [None])[0] or None
            end_text = params.get("end", [None])[0] or None
            try:
                start, end, range_label = resolve_web_range(
                    resolution=resolution, preset=preset, start_text=start_text, end_text=end_text
                )
                html = historical_statistics_page(
                    self.storage, resolution=resolution,
                    preset=None if range_label == "custom" else preset,
                    start=start, end=end, range_label=range_label,
                )
            except ValueError as exc:
                self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST); return
            except RuntimeError as exc:
                self._send_json({"error": str(exc)}, HTTPStatus.SERVICE_UNAVAILABLE); return
            self._send_html(html); return

        route = _ROUTES.get(parsed.path)
        if route is None:
            self._send_json({"error": "not found"}, HTTPStatus.NOT_FOUND); return
        family, request = route
        try:
            freshness = rollup_freshness_token(self.storage, family)
            canonical = _canonical_request(parsed.path, params)
            cache_key = self.statistics_cache.key("json", f"{canonical}|freshness={freshness}")
            payload, cache_hit = self.statistics_cache.get_or_compute(
                cache_key, lambda: request(self.storage, params)
            )
        except ValueError as exc:
            self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST); return
        except RuntimeError as exc:
            self._send_json({"error": str(exc)}, HTTPStatus.SERVICE_UNAVAILABLE); return
        self._send_json(payload, cache_status="HIT" if cache_hit else "MISS")

    def log_message(self, format: str, *args: object) -> None:
        return


def make_statistics_server(storage: StorageBackend, host: str = "127.0.0.1", port: int = 8080) -> ThreadingHTTPServer:
    handler = type(
        "NNTPIntelStatisticsHTTPHandler",
        (StatisticsHTTPHandler,),
        {"storage": storage, "statistics_cache": StatisticsCache()},
    )
    return ThreadingHTTPServer((host, port), handler)


def serve_statistics(database_url: str, *, host: str = "127.0.0.1", port: int = 8080) -> None:
    storage = open_storage(database_url)
    if storage.backend_name != "postgresql":
        raise RuntimeError("production statistics HTTP requires PostgreSQL")
    server = make_statistics_server(storage, host, port)
    try:
        server.serve_forever()
    finally:
        server.server_close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="nntpintel-statistics-api")
    parser.add_argument("--database-url", default=os.environ.get("NNTPINTEL_DATABASE_URL"), help="PostgreSQL URL; defaults to NNTPINTEL_DATABASE_URL")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.database_url:
        raise SystemExit("--database-url or NNTPINTEL_DATABASE_URL is required")
    serve_statistics(args.database_url, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
