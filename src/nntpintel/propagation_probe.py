from __future__ import annotations

import socket
import ssl
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import BinaryIO

from nntpintel.probe import NNTPProtocolError, _parse_status, _readline, _send
from nntpintel.propagation import normalize_message_id, record_presence
from nntpintel.storage import Storage


@dataclass(frozen=True, slots=True)
class PresenceProbeResult:
    observed_at: str
    host: str
    port: int
    transport: str
    message_id: str
    present: bool
    response_code: int | None
    response: str | None
    error: str | None = None


def stat_message_id(
    host: str,
    message_id: str,
    *,
    port: int = 119,
    implicit_tls: bool = False,
    starttls: bool = False,
    timeout: float = 5.0,
) -> PresenceProbeResult:
    if implicit_tls and starttls:
        raise ValueError("implicit_tls and starttls are mutually exclusive")
    if timeout <= 0 or timeout > 15:
        raise ValueError("timeout must be greater than zero and at most 15 seconds")

    message_id = normalize_message_id(message_id)
    observed_at = datetime.now(UTC).isoformat()
    transport = "tls" if implicit_tls else "tcp"
    response_code: int | None = None
    response: str | None = None
    raw_sock: socket.socket | ssl.SSLSocket | None = None
    stream: BinaryIO | None = None

    try:
        raw_sock = socket.create_connection((host, port), timeout=timeout)
        raw_sock.settimeout(timeout)
        context = ssl.create_default_context()
        if implicit_tls:
            raw_sock = context.wrap_socket(raw_sock, server_hostname=host)

        stream = raw_sock.makefile("rwb", buffering=0)
        greeting = _readline(stream)
        greeting_code, _ = _parse_status(greeting)
        if greeting_code not in {200, 201}:
            raise NNTPProtocolError(f"unexpected greeting code {greeting_code}")

        if starttls:
            _send(stream, "STARTTLS")
            line = _readline(stream)
            code, _ = _parse_status(line)
            if code != 382:
                raise NNTPProtocolError(f"STARTTLS rejected: {line}")
            stream.close()
            stream = None
            raw_sock = context.wrap_socket(raw_sock, server_hostname=host)
            transport = "starttls"
            stream = raw_sock.makefile("rwb", buffering=0)

        _send(stream, f"STAT {message_id}")
        response = _readline(stream)
        response_code, _ = _parse_status(response)
        if response_code == 223:
            present = True
            error = None
        elif response_code == 430:
            present = False
            error = None
        else:
            present = False
            error = f"unexpected STAT status {response_code}: {response}"

        try:
            _send(stream, "QUIT")
            _readline(stream)
        except (OSError, NNTPProtocolError):
            pass

        return PresenceProbeResult(
            observed_at=observed_at,
            host=host,
            port=port,
            transport=transport,
            message_id=message_id,
            present=present,
            response_code=response_code,
            response=response,
            error=error,
        )
    except (OSError, ssl.SSLError, NNTPProtocolError) as exc:
        return PresenceProbeResult(
            observed_at=observed_at,
            host=host,
            port=port,
            transport=transport,
            message_id=message_id,
            present=False,
            response_code=response_code,
            response=response,
            error=f"{type(exc).__name__}: {exc}",
        )
    finally:
        if stream is not None:
            try:
                stream.close()
            except OSError:
                pass
        if raw_sock is not None:
            try:
                raw_sock.close()
            except OSError:
                pass


def probe_and_record_presence(
    storage: Storage,
    endpoint_id: int,
    message_id: str,
    *,
    timeout: float = 5.0,
    probe_func: Callable[..., PresenceProbeResult] = stat_message_id,
) -> dict:
    with storage.connect() as conn:
        endpoint = conn.execute(
            """
            SELECT e.id, e.port, e.transport, e.starttls, s.host
            FROM endpoints e
            JOIN servers s ON s.id = e.server_id
            WHERE e.id = ? AND e.enabled = 1 AND s.enabled = 1
            """,
            (endpoint_id,),
        ).fetchone()
    if endpoint is None:
        raise ValueError(f"unknown or disabled endpoint: {endpoint_id}")

    result = probe_func(
        endpoint["host"],
        message_id,
        port=int(endpoint["port"]),
        implicit_tls=endpoint["transport"] == "tls",
        starttls=bool(endpoint["starttls"]),
        timeout=timeout,
    )
    record_presence(
        storage,
        result.message_id,
        endpoint_id,
        observed_at=result.observed_at,
        present=result.present,
        method="stat",
        response_code=result.response_code,
        error=result.error,
    )
    return asdict(result)
