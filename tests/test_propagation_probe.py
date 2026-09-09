import socket
import threading

import pytest

from nntpintel.propagation_probe import (
    PresenceProbeResult,
    probe_and_record_presence,
    stat_message_id,
)
from nntpintel.storage import Storage


def _serve_stat(listener: socket.socket, *, present: bool) -> None:
    conn, _ = listener.accept()
    with conn, conn.makefile("rwb", buffering=0) as stream:
        stream.write(b"200 passive propagation test server\r\n")
        assert stream.readline() == b"STAT <probe@example.test>\r\n"
        if present:
            stream.write(b"223 42 <probe@example.test>\r\n")
        else:
            stream.write(b"430 no such article\r\n")
        assert stream.readline() == b"QUIT\r\n"
        stream.write(b"205 closing\r\n")
        assert stream.readline() == b""


@pytest.mark.parametrize(("present", "code"), [(True, 223), (False, 430)])
def test_stat_message_id_wire_behavior(present, code):
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]

    thread = threading.Thread(target=_serve_stat, args=(listener,), kwargs={"present": present}, daemon=True)
    thread.start()
    result = stat_message_id(
        "127.0.0.1",
        "<probe@example.test>",
        port=port,
        timeout=2.0,
    )
    thread.join(timeout=2)
    listener.close()

    assert not thread.is_alive()
    assert result.error is None
    assert result.present is present
    assert result.response_code == code
    assert result.message_id == "<probe@example.test>"
    assert result.transport == "tcp"


def test_stat_message_id_rejects_unsafe_configuration():
    with pytest.raises(ValueError, match="mutually exclusive"):
        stat_message_id(
            "news.example.test",
            "<probe@example.test>",
            implicit_tls=True,
            starttls=True,
        )
    with pytest.raises(ValueError, match="at most 15"):
        stat_message_id("news.example.test", "<probe@example.test>", timeout=16)


def test_probe_and_record_presence_persists_only_metadata(tmp_path):
    storage = Storage(tmp_path / "nntpintel.db")
    endpoint_id = storage.ensure_endpoint("news.example.test")

    def fake_probe(host, message_id, **kwargs):
        assert host == "news.example.test"
        assert message_id == "<stored@example.test>"
        assert kwargs == {
            "port": 119,
            "implicit_tls": False,
            "starttls": False,
            "timeout": 3.0,
        }
        return PresenceProbeResult(
            observed_at="2026-09-09T03:20:00+00:00",
            host=host,
            port=119,
            transport="tcp",
            message_id=message_id,
            present=True,
            response_code=223,
            response="223 42 <stored@example.test>",
        )

    result = probe_and_record_presence(
        storage,
        endpoint_id,
        "<stored@example.test>",
        timeout=3.0,
        probe_func=fake_probe,
    )
    assert result["present"] is True

    with storage.connect() as conn:
        row = conn.execute(
            """
            SELECT pa.message_id, po.endpoint_id, po.present, po.method,
                   po.response_code, po.error
            FROM propagation_observations po
            JOIN propagation_articles pa ON pa.id = po.article_id
            """
        ).fetchone()
        columns = {item["name"] for item in conn.execute("PRAGMA table_info(propagation_observations)")}
    assert dict(row) == {
        "message_id": "<stored@example.test>",
        "endpoint_id": endpoint_id,
        "present": 1,
        "method": "stat",
        "response_code": 223,
        "error": None,
    }
    assert "response" not in columns
    assert "body" not in columns
    assert "subject" not in columns
