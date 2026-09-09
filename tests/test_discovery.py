from nntpintel.discovery import (
    extract_seeds,
    import_seeds,
    list_sources,
    parse_seed,
    refresh_builtin_source,
    refresh_source,
    set_server_enabled,
)
from nntpintel.storage import Storage


def test_parse_seed_normalizes_transport_and_host():
    assert parse_seed("NEWS.EXAMPLE.TEST") == parse_seed("nntp://news.example.test:119")
    secure = parse_seed("nntps://News.Example.Test")
    assert secure.host == "news.example.test"
    assert secure.port == 563
    assert secure.transport == "tls"


def test_import_is_idempotent_tracks_provenance_and_defaults_disabled(tmp_path):
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

    assert first == {
        "accepted": 2,
        "imported": 2,
        "rejected": 1,
        "added": 2,
        "still_present": 0,
        "missing": 0,
    }
    assert second["accepted"] == 2
    assert second["added"] == 0
    assert second["still_present"] == 2
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
    assert sources[0]["active_server_count"] == 2

    assert storage.due_endpoints("9999-12-31T23:59:59+00:00") == []
    assert set_server_enabled(storage, "news.example.test", True)
    due = storage.due_endpoints("9999-12-31T23:59:59+00:00")
    assert {row["host"] for row in due} == {"news.example.test"}


def test_discovery_does_not_disable_preexisting_active_server(tmp_path):
    storage = Storage(tmp_path / "nntpintel.db")
    storage.ensure_endpoint("news.example.test")
    import_seeds(storage, ["news.example.test"], source="source-a")

    due = storage.due_endpoints("9999-12-31T23:59:59+00:00")
    assert {row["host"] for row in due} == {"news.example.test"}


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


def test_open_nntp_html_adapter_extracts_only_nntp_like_hosts():
    html = """
    <table>
      <tr><td>news.solani.org</td><td>text</td></tr>
      <tr><td>news.eternal-september.org</td><td>registration</td></tr>
      <tr><td>usenet.example.net</td><td>test</td></tr>
      <tr><td>www.example.net</td><td>website</td></tr>
    </table>
    """
    assert extract_seeds(html, "open-nntp-html") == [
        "news.solani.org",
        "news.eternal-september.org",
        "usenet.example.net",
    ]


def test_snapshot_refresh_tracks_added_present_and_missing(tmp_path):
    storage = Storage(tmp_path / "nntpintel.db")
    first = refresh_source(
        storage,
        source="example-html",
        source_ref="https://example.test/list",
        adapter="open-nntp-html",
        content="<td>news.one.test</td><td>news.two.test</td>",
    )
    second = refresh_source(
        storage,
        source="example-html",
        source_ref="https://example.test/list",
        adapter="open-nntp-html",
        content="<td>news.two.test</td><td>news.three.test</td>",
    )

    assert first["added"] == 2
    assert second["added"] == 1
    assert second["still_present"] == 1
    assert second["missing"] == 1
    source = list_sources(storage)[0]
    assert source["server_count"] == 3
    assert source["active_server_count"] == 2
    assert storage.due_endpoints("9999-12-31T23:59:59+00:00") == []


def test_builtin_adapter_can_be_qualified_without_network(tmp_path):
    storage = Storage(tmp_path / "nntpintel.db")
    result = refresh_builtin_source(
        storage,
        "vivil-open-nntp",
        content="<td>news.solani.org</td><td>news.eternal-september.org</td>",
    )
    assert result["accepted"] == 2
    assert result["added"] == 2
    assert list_sources(storage)[0]["name"] == "vivil-open-nntp"
