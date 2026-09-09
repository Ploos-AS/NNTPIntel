import socket
import sqlite3
import threading
from datetime import UTC, datetime

from nntpintel.groups import GroupInventory, GroupRecord, inventory_groups
from nntpintel.storage import Storage


def _serve_group_inventory(listener: socket.socket) -> None:
    conn, _ = listener.accept()
    with conn:
        stream = conn.makefile("rwb", buffering=0)
        stream.write(b"200 group qualification server\r\n")
        while True:
            line = stream.readline()
            if not line:
                return
            command = line.decode("ascii").strip().upper()
            if command == "LIST ACTIVE":
                stream.write(b"215 list follows\r\n")
                stream.write(b"comp.lang.python 12345 12000 y\r\n")
                stream.write(b"alt.test 42 1 n\r\n")
                stream.write(b".\r\n")
            elif command == "LIST NEWSGROUPS":
                stream.write(b"215 descriptions follow\r\n")
                stream.write(b"comp.lang.python Python discussion\r\n")
                stream.write(b"alt.test Test group\r\n")
                stream.write(b".\r\n")
            elif command.startswith("NEWGROUPS "):
                stream.write(b"231 new groups follow\r\n")
                stream.write(b"comp.lang.python 12345 12000 y\r\n")
                stream.write(b".\r\n")
            elif command == "QUIT":
                stream.write(b"205 closing\r\n")
                return
            else:
                stream.write(b"500 unsupported\r\n")


def test_group_inventory_runtime_and_persistence(tmp_path):
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]

    thread = threading.Thread(target=_serve_group_inventory, args=(listener,), daemon=True)
    thread.start()
    inventory = inventory_groups(
        "127.0.0.1",
        port=port,
        timeout=1.0,
        newgroups_since=datetime(2026, 9, 8, tzinfo=UTC),
    )
    thread.join(timeout=2)
    listener.close()

    assert inventory.error is None
    assert [group.name for group in inventory.groups] == ["alt.test", "comp.lang.python"]
    assert inventory.new_groups == ["comp.lang.python"]
    python_group = inventory.groups[1]
    assert python_group.high == 12345
    assert python_group.low == 12000
    assert python_group.status == "y"
    assert python_group.description == "Python discussion"
    assert python_group.hierarchy == "comp"

    storage = Storage(tmp_path / "nntpintel.db")
    endpoint_id = storage.ensure_endpoint("127.0.0.1", port=port)
    assert storage.record_group_inventory(endpoint_id, inventory) == 2
    assert storage.group_count() == 2
    assert storage.hierarchy_count() == 2
    assert storage.group_event_count() == 2

    with storage.connect() as conn:
        snapshots = conn.execute(
            """
            SELECT n.name, g.high_water, g.low_water, g.posting_status, g.description
            FROM group_snapshots g
            JOIN newsgroups n ON n.id = g.newsgroup_id
            ORDER BY n.name
            """
        ).fetchall()
    assert snapshots[1]["name"] == "comp.lang.python"
    assert snapshots[1]["high_water"] == 12345
    assert snapshots[1]["description"] == "Python discussion"


def test_schema_v1_database_migrates_to_v2(tmp_path):
    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE schema_version (version INTEGER NOT NULL)")
        conn.execute("INSERT INTO schema_version(version) VALUES (1)")
        conn.commit()

    storage = Storage(path)
    with storage.connect() as conn:
        version = conn.execute("SELECT version FROM schema_version").fetchone()["version"]
        tables = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
        }

    assert version == 2
    assert {"hierarchies", "newsgroups", "group_snapshots", "group_events"} <= tables


def test_group_inventory_tracks_changes_and_disappearance(tmp_path):
    storage = Storage(tmp_path / "nntpintel.db")
    endpoint_id = storage.ensure_endpoint("news.example.test")

    first = GroupInventory(
        observed_at=datetime(2026, 9, 9, 1, 0, tzinfo=UTC).isoformat(),
        host="news.example.test",
        port=119,
        transport="tcp",
        groups=[
            GroupRecord("comp.test", high=10, low=1, status="y"),
            GroupRecord("alt.test", high=5, low=1, status="y"),
        ],
    )
    second = GroupInventory(
        observed_at=datetime(2026, 9, 9, 2, 0, tzinfo=UTC).isoformat(),
        host="news.example.test",
        port=119,
        transport="tcp",
        groups=[GroupRecord("comp.test", high=11, low=1, status="y")],
    )

    storage.record_group_inventory(endpoint_id, first)
    storage.record_group_inventory(endpoint_id, second)

    with storage.connect() as conn:
        row = conn.execute(
            "SELECT first_seen_at, last_seen_at FROM newsgroups WHERE name = 'comp.test'"
        ).fetchone()
        snapshots = conn.execute(
            "SELECT high_water FROM group_snapshots WHERE newsgroup_id = "
            "(SELECT id FROM newsgroups WHERE name = 'comp.test') ORDER BY observed_at"
        ).fetchall()
        events = conn.execute(
            """
            SELECT n.name, e.event_type
            FROM group_events e
            JOIN newsgroups n ON n.id = e.newsgroup_id
            ORDER BY e.id
            """
        ).fetchall()

    assert row["first_seen_at"] == first.observed_at
    assert row["last_seen_at"] == second.observed_at
    assert [item["high_water"] for item in snapshots] == [10, 11]
    assert [(item["name"], item["event_type"]) for item in events] == [
        ("comp.test", "appeared"),
        ("alt.test", "appeared"),
        ("comp.test", "changed"),
        ("alt.test", "disappeared"),
    ]
