import json
import threading
from datetime import UTC, datetime, timedelta
from urllib.request import urlopen

from nntpintel.api import make_server
from nntpintel.candidate_observability import list_candidate_observability
from nntpintel.candidate_web import candidates_page
from nntpintel.discovery import import_seeds
from nntpintel.storage import Storage


def _add_qualification(storage: Storage, host: str, classification: str, observed_at: datetime) -> None:
    with storage.connect() as conn:
        endpoint_id = conn.execute(
            """
            SELECT e.id
            FROM endpoints e
            JOIN servers s ON s.id = e.server_id
            WHERE s.host = ?
            ORDER BY e.id
            LIMIT 1
            """,
            (host,),
        ).fetchone()["id"]
        conn.execute(
            """
            INSERT INTO candidate_qualifications(endpoint_id, observed_at, classification)
            VALUES (?, ?, ?)
            """,
            (endpoint_id, observed_at.isoformat(), classification),
        )
        conn.commit()


def test_candidate_observability_reports_due_and_promotion_readiness(tmp_path):
    storage = Storage(tmp_path / "nntpintel.db")
    import_seeds(storage, ["news.example.test"], source="test-source")
    now = datetime(2026, 9, 9, 5, 0, tzinfo=UTC)
    _add_qualification(storage, "news.example.test", "reachable", now - timedelta(hours=7))
    _add_qualification(storage, "news.example.test", "reachable", now - timedelta(hours=5))

    item = list_candidate_observability(storage, now=now)[0]
    assert item["latest_classification"] == "reachable"
    assert item["latest_age_seconds"] == 5 * 3600
    assert item["qualification_due"] is False
    assert item["next_qualification_at"] == (now + timedelta(hours=1)).isoformat()
    assert item["recent_reachable_count"] == 2
    assert item["promotion_ready"] is True
    assert item["promotion_blockers"] == []


def test_candidate_observability_explains_blockers(tmp_path):
    storage = Storage(tmp_path / "nntpintel.db")
    import_seeds(storage, ["news.example.test"], source="test-source")
    now = datetime(2026, 9, 9, 5, 0, tzinfo=UTC)
    _add_qualification(storage, "news.example.test", "unreachable", now - timedelta(hours=8))

    item = list_candidate_observability(storage, now=now)[0]
    assert item["qualification_due"] is True
    assert item["promotion_ready"] is False
    assert "reachable:0/2" in item["promotion_blockers"]
    assert "latest:unreachable" in item["promotion_blockers"]


def test_candidates_api_and_web_expose_observability(tmp_path):
    storage = Storage(tmp_path / "nntpintel.db")
    import_seeds(storage, ["news.example.test"], source="test-source")
    now = datetime.now(UTC)
    _add_qualification(storage, "news.example.test", "reachable", now - timedelta(hours=7))
    _add_qualification(storage, "news.example.test", "reachable", now - timedelta(hours=5))

    server = make_server(storage, "127.0.0.1", 0)
    host, port = server.server_address
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with urlopen(f"http://{host}:{port}/candidates", timeout=2) as response:
            payload = json.load(response)
        assert payload[0]["promotion_ready"] is True
        assert payload[0]["qualification_due"] is False
        assert payload[0]["recent_reachable_count"] == 2
        assert payload[0]["next_qualification_at"]

        html = candidates_page(storage)
        assert "Promotion ready" in html
        assert "Next qualification" in html
        assert "Recent reachable" in html
        assert "news.example.test" in html
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
