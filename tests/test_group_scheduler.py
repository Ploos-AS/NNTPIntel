import socket
import threading
from datetime import UTC, datetime, timedelta

from nntpintel.scheduler import SchedulerConfig, run_group_inventories
from nntpintel.storage import Storage


def _serve_groups(listener: socket.socket) -> None:
    conn, _ = listener.accept()
    with conn:
        stream = conn.makefile("rwb", buffering=0)
        stream.write(b"200 scheduler group server\r\n")
        while True:
            line = stream.readline()
            if not line:
                return
            command = line.decode("ascii").strip().upper()
            if command == "LIST ACTIVE":
                stream.write(b"215 list follows\r\n")
                stream.write(b"comp.test 10 1 y\r\n")
                stream.write(b".\r\n")
            elif command == "LIST NEWSGROUPS":
                stream.write(b"215 descriptions follow\r\n")
                stream.write(b"comp.test Scheduler test group\r\n")
                stream.write(b".\r\n")
            elif command == "QUIT":
                stream.write(b"205 closing\r\n")
                return
            else:
                stream.write(b"500 unsupported\r\n")


def test_group_inventory_runs_only_when_due(tmp_path):
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]

    storage = Storage(tmp_path / "nntpintel.db")
    endpoint_id = storage.ensure_endpoint(
        "127.0.0.1",
        port=port,
        timeout_seconds=1.0,
        group_interval_seconds=3600,
    )

    thread = threading.Thread(target=_serve_groups, args=(listener,), daemon=True)
    thread.start()
    assert run_group_inventories(storage, config=SchedulerConfig(group_batch_size=1)) == 1
    thread.join(timeout=2)
    listener.close()

    assert storage.group_count() == 1
    assert storage.group_event_count() == 1
    assert run_group_inventories(storage, config=SchedulerConfig(group_batch_size=1)) == 0

    with storage.connect() as conn:
        row = conn.execute(
            "SELECT last_inventory_at, next_inventory_at, interval_seconds "
            "FROM group_inventory_schedule WHERE endpoint_id = ?",
            (endpoint_id,),
        ).fetchone()

    last_at = datetime.fromisoformat(row["last_inventory_at"])
    next_at = datetime.fromisoformat(row["next_inventory_at"])
    assert row["interval_seconds"] == 3600
    assert next_at >= last_at + timedelta(seconds=3600)
    assert last_at.tzinfo == UTC
