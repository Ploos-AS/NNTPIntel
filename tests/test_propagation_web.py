import json
import threading
from datetime import UTC, datetime
from urllib.error import HTTPError
from urllib.request import urlopen

from nntpintel.api import make_server
from nntpintel.propagation import record_presence, register_article
from nntpintel.propagation_campaigns import create_campaign
from nntpintel.storage import Storage


def _get_json(url: str) -> object:
    with urlopen(url, timeout=2) as response:
        assert response.headers.get_content_type() == "application/json"
        return json.load(response)


def _get_html(url: str) -> str:
    with urlopen(url, timeout=2) as response:
        assert response.headers.get_content_type() == "text/html"
        return response.read().decode("utf-8")


def _propagation_storage(tmp_path) -> tuple[Storage, int]:
    storage = Storage(tmp_path / "nntpintel.db")
    first = storage.ensure_endpoint("news-a.example.test")
    second = storage.ensure_endpoint("news-b.example.test")
    message_id = "<web-propagation@example.test>"
    article_id = register_article(storage, message_id, newsgroup="comp.test")
    record_presence(
        storage,
        message_id,
        second,
        observed_at="2026-09-09T05:00:05+00:00",
        present=False,
        response_code=430,
    )
    record_presence(
        storage,
        message_id,
        first,
        observed_at="2026-09-09T05:00:10+00:00",
        present=True,
        response_code=223,
    )
    record_presence(
        storage,
        message_id,
        second,
        observed_at="2026-09-09T05:00:42+00:00",
        present=True,
        response_code=223,
    )
    create_campaign(
        storage,
        message_id,
        [first, second],
        interval_seconds=300,
        ttl_seconds=3600,
        stop_after_visible=2,
        now=datetime(2026, 9, 9, 5, 0, tzinfo=UTC),
    )
    return storage, article_id


def test_propagation_api_exposes_articles_detail_and_campaigns(tmp_path):
    storage, article_id = _propagation_storage(tmp_path)
    server = make_server(storage, "127.0.0.1", 0)
    host, port = server.server_address
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://{host}:{port}"

    try:
        articles = _get_json(f"{base}/propagation/articles")
        assert articles[0]["id"] == article_id
        assert articles[0]["message_id"] == "<web-propagation@example.test>"
        assert articles[0]["observation_count"] == 3
        assert articles[0]["visible_endpoint_count"] == 2

        detail = _get_json(f"{base}/propagation/articles/{article_id}")
        assert detail["newsgroup"] == "comp.test"
        assert detail["first_visibility_at"] == "2026-09-09T05:00:10+00:00"
        assert [item["delay_seconds"] for item in detail["endpoints"]] == [0.0, 32.0]
        assert [bool(item["present"]) for item in detail["observations"]] == [False, True, True]
        assert len(detail["campaigns"]) == 1

        campaigns = _get_json(f"{base}/propagation/campaigns")
        assert campaigns[0]["message_id"] == "<web-propagation@example.test>"
        assert campaigns[0]["endpoint_ids"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_propagation_web_renders_delay_and_presence_timeline(tmp_path):
    storage, article_id = _propagation_storage(tmp_path)
    server = make_server(storage, "127.0.0.1", 0)
    host, port = server.server_address
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://{host}:{port}"

    try:
        overview = _get_html(f"{base}/web/propagation")
        assert "Propagation articles" in overview
        assert "Campaigns" in overview
        assert "&lt;web-propagation@example.test&gt;" in overview
        assert f'href="/web/propagation/{article_id}"' in overview

        detail = _get_html(f"{base}/web/propagation/{article_id}")
        assert "Measured propagation delay" in detail
        assert "Presence timeline" in detail
        assert "news-a.example.test:119" in detail
        assert "news-b.example.test:119" in detail
        assert ">32.0<" in detail
        assert "not present" in detail
        assert "present" in detail
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_unknown_propagation_article_returns_404(tmp_path):
    storage = Storage(tmp_path / "nntpintel.db")
    server = make_server(storage, "127.0.0.1", 0)
    host, port = server.server_address
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        try:
            _get_json(f"http://{host}:{port}/propagation/articles/999")
        except HTTPError as exc:
            assert exc.code == 404
            assert json.load(exc) == {"error": "not found"}
        else:
            raise AssertionError("expected HTTP 404")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
