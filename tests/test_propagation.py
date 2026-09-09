import pytest

from nntpintel.propagation import (
    normalize_message_id,
    propagation_summary,
    record_presence,
    register_article,
)
from nntpintel.storage import SCHEMA_VERSION, Storage


def test_schema_v6_contains_propagation_tables(tmp_path):
    storage = Storage(tmp_path / "nntpintel.db")
    with storage.connect() as conn:
        version = conn.execute("SELECT version FROM schema_version").fetchone()["version"]
        tables = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
    assert version == SCHEMA_VERSION == 6
    assert {
        "propagation_articles",
        "propagation_observations",
        "propagation_campaigns",
        "propagation_campaign_endpoints",
    } <= tables


def test_normalize_message_id_rejects_invalid_values():
    assert normalize_message_id(" <abc@example.test> ") == "<abc@example.test>"
    with pytest.raises(ValueError):
        normalize_message_id("abc@example.test")
    with pytest.raises(ValueError):
        normalize_message_id("<abc @example.test>")


def test_register_article_is_idempotent_and_never_stores_body(tmp_path):
    storage = Storage(tmp_path / "nntpintel.db")
    first = register_article(
        storage,
        "<abc@example.test>",
        newsgroup="comp.test",
        article_date="2026-09-09T01:00:00+00:00",
    )
    second = register_article(storage, "<abc@example.test>")
    assert first == second

    with storage.connect() as conn:
        row = conn.execute("SELECT * FROM propagation_articles").fetchone()
        columns = {item["name"] for item in conn.execute("PRAGMA table_info(propagation_articles)")}
    assert row["newsgroup"] == "comp.test"
    assert "body" not in columns
    assert "subject" not in columns


def test_summary_computes_measured_delay_from_first_visibility(tmp_path):
    storage = Storage(tmp_path / "nntpintel.db")
    first_endpoint = storage.ensure_endpoint("news-a.example.test", port=119)
    second_endpoint = storage.ensure_endpoint("news-b.example.test", port=563, transport="tls")
    message_id = "<propagation@example.test>"

    register_article(storage, message_id, newsgroup="comp.test")
    record_presence(
        storage,
        message_id,
        second_endpoint,
        observed_at="2026-09-09T03:00:08+00:00",
        present=False,
        response_code=430,
    )
    record_presence(
        storage,
        message_id,
        first_endpoint,
        observed_at="2026-09-09T03:00:10+00:00",
        present=True,
        response_code=223,
    )
    record_presence(
        storage,
        message_id,
        second_endpoint,
        observed_at="2026-09-09T03:00:42+00:00",
        present=True,
        response_code=223,
    )
    record_presence(
        storage,
        message_id,
        first_endpoint,
        observed_at="2026-09-09T03:01:00+00:00",
        present=True,
        response_code=223,
    )

    summary = propagation_summary(storage, message_id)
    assert summary["observation_count"] == 4
    assert summary["visible_endpoint_count"] == 2
    assert summary["first_visibility_at"] == "2026-09-09T03:00:10+00:00"
    assert summary["endpoints"][0]["host"] == "news-a.example.test"
    assert summary["endpoints"][0]["delay_seconds"] == 0.0
    assert summary["endpoints"][1]["host"] == "news-b.example.test"
    assert summary["endpoints"][1]["delay_seconds"] == 32.0


def test_record_presence_rejects_unknown_endpoint_and_method(tmp_path):
    storage = Storage(tmp_path / "nntpintel.db")
    with pytest.raises(ValueError, match="unknown endpoint"):
        record_presence(storage, "<abc@example.test>", 999, present=True)

    endpoint_id = storage.ensure_endpoint("news.example.test")
    with pytest.raises(ValueError, match="method"):
        record_presence(
            storage,
            "<abc@example.test>",
            endpoint_id,
            present=True,
            method="article",
        )
