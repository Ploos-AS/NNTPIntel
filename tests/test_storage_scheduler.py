import socket
import threading
from contextlib import closing
from datetime import UTC, datetime, timedelta

from nntpintel.probe import ProbeObservation
from nntpintel.scheduler import SchedulerConfig, _next_probe_time, run_once
from nntpintel.storage import Storage


def _serve_once(listener: socket.socket) -> None:
    conn, _ = listener.accept()
    with conn:
        stream = conn.makefile("rwb", buffering=0)
        stream.write(b"200 NNTPIntel qualification server\r\n")
        while True:
            line = stream.readline()
            if not line:
                return
            command = line.decode("ascii").strip().upper()
            if command == "CAPABILITIES":
                stream.write(b"101 Capability list follows\r\n")
                stream.write(b"VERSION 2\r\n")
                stream.write(b"READER\r\n")
                stream.write(b".\r\n")
            elif command == "MODE READER":
                stream.write(b"200 Reader mode\r\n")
            elif command == "QUIT":
                stream.write(b"205 closing connection\r\n")
                return
            else:
                stream.write(b"500 unsupported\r\n")


def _listener(port: int = 0) -> socket.socket:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", port))
    listener.listen(1)
    return listener


def _force_due(storage: Storage, endpoint_id: int) -> None:
    with closing(storage.connect()) as conn:
        conn.execute(
            "UPDATE endpoints SET next_probe_at = ? WHERE id = ?",
            ((datetime.now(UTC) - timedelta(seconds=1)).isoformat(), endpoint_id),
        )
        conn.commit()


def test_storage_creates_endpoint_and_records_observation(tmp_path):
    storage = Storage(tmp_path / "nntpintel.db")
    endpoint_id = storage.ensure_endpoint("news.example.test", interval_seconds=60)

    observation = ProbeObservation(
        observed_at=datetime.now(UTC).isoformat(),
        host="news.example.test",
        port=119,
        transport="tcp",
        greeting_code=200,
        greeting="200 test server",
        posting_allowed=True,
        capabilities=["VERSION 2", "READER"],
        mode_reader_code=200,
        mode_reader_response="200 reader mode",
    )
    storage.record_observation(endpoint_id, observation)

    assert storage.observation_count() == 1
    endpoints = list(storage.list_endpoints())
    assert len(endpoints) == 1
    assert endpoints[0]["host"] == "news.example.test"


def test_due_endpoint_is_returned(tmp_path):
    storage = Storage(tmp_path / "nntpintel.db")
    storage.ensure_endpoint("news.example.test")

    due = storage.due_endpoints(datetime.now(UTC).isoformat())
    assert len(due) == 1
    assert due[0]["host"] == "news.example.test"


def test_success_schedule_uses_base_interval():
    now = datetime(2026, 9, 9, tzinfo=UTC)
    result = _next_probe_time(
        now=now,
        interval_seconds=60,
        consecutive_failures=0,
        max_backoff_seconds=3600,
    )
    assert result == now + timedelta(seconds=60)


def test_failure_schedule_uses_exponential_backoff_and_cap():
    now = datetime(2026, 9, 9, tzinfo=UTC)
    result = _next_probe_time(
        now=now,
        interval_seconds=60,
        consecutive_failures=3,
        max_backoff_seconds=3600,
    )
    assert result == now + timedelta(seconds=480)

    capped = _next_probe_time(
        now=now,
        interval_seconds=60,
        consecutive_failures=20,
        max_backoff_seconds=3600,
    )
    assert capped == now + timedelta(seconds=3600)


def test_scheduler_runtime_failure_backoff_and_recovery(tmp_path):
    storage = Storage(tmp_path / "nntpintel.db")
    listener = _listener()
    port = listener.getsockname()[1]
    endpoint_id = storage.ensure_endpoint(
        "127.0.0.1",
        port=port,
        interval_seconds=1,
        timeout_seconds=0.25,
    )
    config = SchedulerConfig(max_backoff_seconds=60)

    thread = threading.Thread(target=_serve_once, args=(listener,), daemon=True)
    thread.start()
    assert run_once(storage, config=config) == 1
    thread.join(timeout=2)
    listener.close()

    endpoint = list(storage.list_endpoints())[0]
    assert endpoint["consecutive_failures"] == 0
    assert storage.observation_count() == 1

    _force_due(storage, endpoint_id)
    assert run_once(storage, config=config) == 1
    endpoint = list(storage.list_endpoints())[0]
    assert endpoint["consecutive_failures"] == 1
    failure_next = datetime.fromisoformat(endpoint["next_probe_at"])
    failure_last = datetime.fromisoformat(endpoint["last_probe_at"])
    assert failure_next >= failure_last + timedelta(seconds=2)
    assert storage.observation_count() == 2

    listener = _listener(port)
    thread = threading.Thread(target=_serve_once, args=(listener,), daemon=True)
    thread.start()
    _force_due(storage, endpoint_id)
    assert run_once(storage, config=config) == 1
    thread.join(timeout=2)
    listener.close()

    endpoint = list(storage.list_endpoints())[0]
    assert endpoint["consecutive_failures"] == 0
    recovery_next = datetime.fromisoformat(endpoint["next_probe_at"])
    recovery_last = datetime.fromisoformat(endpoint["last_probe_at"])
    assert recovery_next >= recovery_last + timedelta(seconds=1)
    assert recovery_next < recovery_last + timedelta(seconds=2)
    assert storage.observation_count() == 3
