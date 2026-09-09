import socket
import threading
from io import BytesIO

import pytest

from nntpintel.probe import (
    NNTPProtocolError,
    _parse_status,
    _read_multiline,
    _readline,
    probe,
    qualification_probe,
)


def test_parse_status():
    assert _parse_status("200 posting allowed") == (200, "posting allowed")
    assert _parse_status("201") == (201, "")


def test_parse_status_rejects_invalid_line():
    with pytest.raises(NNTPProtocolError):
        _parse_status("hello")


def test_readline_decodes_and_strips_crlf():
    assert _readline(BytesIO(b"200 hello\r\n")) == "200 hello"


def test_multiline_unstuffs_dot_lines():
    stream = BytesIO(b"VERSION 2\r\n..leading-dot\r\n.\r\n")
    assert _read_multiline(stream) == ["VERSION 2", ".leading-dot"]


def test_probe_end_to_end_against_local_nntp_server():
    ready = threading.Event()
    state: dict[str, int] = {}

    def server() -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen(1)
            state["port"] = listener.getsockname()[1]
            ready.set()

            conn, _ = listener.accept()
            with conn, conn.makefile("rwb", buffering=0) as stream:
                stream.write(b"200 local test server ready\r\n")

                assert stream.readline() == b"CAPABILITIES\r\n"
                stream.write(
                    b"101 Capability list follows\r\n"
                    b"VERSION 2\r\n"
                    b"READER\r\n"
                    b"POST\r\n"
                    b".\r\n"
                )

                assert stream.readline() == b"MODE READER\r\n"
                stream.write(b"200 Reader mode acknowledged\r\n")

                assert stream.readline() == b"QUIT\r\n"
                stream.write(b"205 closing connection\r\n")

    thread = threading.Thread(target=server, daemon=True)
    thread.start()
    assert ready.wait(timeout=2)

    observation = probe("127.0.0.1", port=state["port"], timeout=2)
    thread.join(timeout=2)

    assert not thread.is_alive()
    assert observation.error is None
    assert observation.greeting_code == 200
    assert observation.posting_allowed is True
    assert observation.capabilities == ["VERSION 2", "READER", "POST"]
    assert observation.mode_reader_code == 200
    assert observation.transport == "tcp"
    assert observation.connect_ms is not None


def test_qualification_probe_stops_after_capabilities_and_quit():
    ready = threading.Event()
    state: dict[str, int] = {}

    def server() -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen(1)
            state["port"] = listener.getsockname()[1]
            ready.set()

            conn, _ = listener.accept()
            with conn, conn.makefile("rwb", buffering=0) as stream:
                stream.write(b"201 local qualification server ready\r\n")
                assert stream.readline() == b"CAPABILITIES\r\n"
                stream.write(
                    b"101 Capability list follows\r\n"
                    b"VERSION 2\r\n"
                    b"READER\r\n"
                    b".\r\n"
                )
                assert stream.readline() == b"QUIT\r\n"
                stream.write(b"205 closing connection\r\n")
                assert stream.readline() == b""

    thread = threading.Thread(target=server, daemon=True)
    thread.start()
    assert ready.wait(timeout=2)

    observation = qualification_probe("127.0.0.1", port=state["port"], timeout=2)
    thread.join(timeout=2)

    assert not thread.is_alive()
    assert observation.error is None
    assert observation.greeting_code == 201
    assert observation.posting_allowed is False
    assert observation.capabilities == ["VERSION 2", "READER"]
    assert observation.mode_reader_code is None
    assert observation.mode_reader_response is None
