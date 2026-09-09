from nntpintel.discovery import import_seeds, list_sources, parse_seed, set_server_enabled
from nntpintel.storage import Storage


def test_parse_seed_normalizes_transport_and_host():
    assert parse_seed("NEWS.EXAMPLE.TEST") == parse_seed("nntp://news.example.test:119")
    secure = parse_seed("nntps://News.Example.Test")
    assert secure.host == "news.example.test"
    assert secure.port == 563
    assert secure.transport == "tls"


def test_import_is_idempotent_and_tracks_provenance(tmp_path):
    storage = Storage(tmp_path / "nntpintel.db")
    seeds = [
        "# public list",
        "news.example.test",
        "NEWS.EXAMPLE.TEST:119",
        "nntps://secure.example.test",
        "not a valid host name",
    ]

    first = import_seeds(
        storage,
        seeds,
        source="example-list",
        source_ref="https://example.test/nntp-list",
    )
    second = import_seeds(
        storage,
        seeds,
        source="example-list",
        source_ref="https://example.test/nntp-list",
    )

    assert first == {"accepted": 2, "imported": 2, "rejected": 1}
    assert second == first
    endpoints = list(storage.list_endpoints())
    assert len(endpoints) == 2
    assert {row["host"] for row in endpoints} == {
        "news.example.test",
        "secure.example.test",
    }

    sources = list_sources(storage)
    assert sources[0]["name"] == "example-list"
    assert sources[0]["source_ref"] == "https://example.test/nntp-list"
    assert sources[0]["server_count"] == 2

    assert set_server_enabled(storage, "NEWS.EXAMPLE.TEST", False)
    due = storage.due_endpoints("9999-12-31T23:59:59+00:00")
    assert {row["host"] for row in due} == {"secure.example.test"}
    assert set_server_enabled(storage, "news.example.test", True)
    assert len(storage.due_endpoints("9999-12-31T23:59:59+00:00")) == 2


def test_same_server_can_have_multiple_sources(tmp_path):
    storage = Storage(tmp_path / "nntpintel.db")
    import_seeds(storage, ["news.example.test"], source="source-a")
    import_seeds(storage, ["news.example.test"], source="source-b")

    sources = list_sources(storage)
    assert [(row["name"], row["server_count"]) for row in sources] == [
        ("source-a", 1),
        ("source-b", 1),
    ]
    assert len(list(storage.list_endpoints())) == 1
