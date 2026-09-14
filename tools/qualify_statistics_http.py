from __future__ import annotations

import json
import os
import threading
from urllib.request import urlopen

from nntpintel.statistics_http import make_statistics_server
from nntpintel.storage_backend import open_storage


def _json(url: str) -> dict:
    with urlopen(url, timeout=5) as response:
        assert response.status == 200
        return json.load(response)


def main() -> int:
    database_url = os.environ["NNTPINTEL_DATABASE_URL"]
    storage = open_storage(database_url)
    assert storage.backend_name == "postgresql"

    server = make_statistics_server(storage, "127.0.0.1", 0)
    host, port = server.server_address
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://{host}:{port}"

    try:
        health = _json(f"{base}/healthz")
        assert health == {"status": "ok", "backend": "postgresql"}

        endpoints = {
            "servers": "server_availability_latency",
            "groups": "group_hierarchy_inventory_changes",
            "protocol": "protocol_tls_capabilities",
            "propagation": "propagation_incidents_campaigns",
            "topology": "topology_evidence_incidents",
        }
        for name, metric_family in endpoints.items():
            payload = _json(f"{base}/api/v1/statistics/{name}?resolution=day")
            assert payload["api_version"] == "v1"
            assert payload["metric_family"] == metric_family
            assert payload["resolution"] == "day"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    print("M9.0 POSTGRESQL STATISTICS HTTP: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
