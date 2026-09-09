import json
import threading
from datetime import UTC, datetime
from urllib.error import HTTPError
from urllib.request import urlopen

from nntpintel.api import make_server
from nntpintel.groups import GroupInventory, GroupRecord
from nntpintel.storage import Storage


def _get_json(url: str) -> object:
    with urlopen(url, timeout=2) as response:
        assert response.headers.get_content_type() == "application/json"
        return json.load(response)


def test_api_lists_core_resources_and_server_detail(tmp_path):
    storage = Storage(tmp_path / "nntpintel.db")
    endpoint_id = storage.ensure_endpoint("news.example.test", port=119)
    inventory = GroupInventory(
        observed_at=datetime(2026, 9, 9, 3, 0, tzinfo=UTC).isoformat(),
        host="news.example.test",
        port=119,
        transport="tcp",
        groups=[
            GroupRecord(
                "comp.lang.python",
                high=123,
                low=100,
                status="y",
                description="Python discussion",
            )
        ],
    )
    storage.record_group_inventory(endpoint_id, inventory)

    server = make_server(storage, "127.0.0.1", 0)
    host, port = server.server_address
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://{host}:{port}"

    try:
        assert _get_json(f"{base}/healthz") == {"status": "ok"}

        servers = _get_json(f"{base}/servers")
        assert servers[0]["host"] == "news.example.test"
        assert servers[0]["endpoint_count"] == 1
        server_id = servers[0]["id"]

        endpoints = _get_json(f"{base}/endpoints")
        assert endpoints[0]["host"] == "news.example.test"

        groups = _get_json(f"{base}/groups")
        assert groups[0]["name"] == "comp.lang.python"
        assert groups[0]["hierarchy"] == "comp"
        assert groups[0]["high_water"] == 123
        assert groups[0]["description"] == "Python discussion"

        hierarchies = _get_json(f"{base}/hierarchies")
        assert hierarchies == [
            {
                "first_seen_at": inventory.observed_at,
                "group_count": 1,
                "id": hierarchies[0]["id"],
                "last_seen_at": inventory.observed_at,
                "name": "comp",
            }
        ]

        events = _get_json(f"{base}/events")
        assert events[0]["event_type"] == "appeared"
        assert events[0]["newsgroup"] == "comp.lang.python"

        detail = _get_json(f"{base}/servers/{server_id}")
        assert detail["host"] == "news.example.test"
        assert detail["endpoints"][0]["port"] == 119
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_api_returns_json_404(tmp_path):
    storage = Storage(tmp_path / "nntpintel.db")
    server = make_server(storage, "127.0.0.1", 0)
    host, port = server.server_address
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        try:
            _get_json(f"http://{host}:{port}/missing")
        except HTTPError as exc:
            assert exc.code == 404
            assert json.load(exc) == {"error": "not found"}
        else:
            raise AssertionError("expected HTTP 404")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
