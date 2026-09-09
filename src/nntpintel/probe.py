from __future__ import annotations

import socket
import ssl
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import BinaryIO

MAX_LINE = 16 * 1024
MAX_MULTILINE_BYTES = 512 * 1024


@dataclass(slots=True)
class TLSObservation:
    enabled: bool = False
    mode: str | None = None
    protocol: str | None = None
    cipher: str | None = None
    peer_subject: str | None = None
    peer_issuer: str | None = None
    not_before: str | None = None
    not_after: str | None = None


@dataclass(slots=True)
class ProbeObservation:
    observed_at: str
    host: str
    port: int
    transport: str
    connect_ms: float | None = None
    greeting_code: int | None = None
    greeting: str | None = None
    posting_allowed: bool | None = None
    capabilities: list[str] = field(default_factory=list)
    mode_reader_code: int | None = None
    mode_reader_response: str | None = None
    tls: TLSObservation = field(default_factory=TLSObservation)
    error: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


class NNTPProtocolError(RuntimeError):
    pass


def _readline(stream: BinaryIO) -> str:
    raw = stream.readline(MAX_LINE + 1)
    if not raw:
        raise NNTPProtocolError("connection closed while reading response")
    if len(raw) > MAX_LINE:
        raise NNTPProtocolError("NNTP response line exceeds safety limit")
    return raw.decode("utf-8", errors="replace").rstrip("\r\n")


def _parse_status(line: str) -> tuple[int, str]:
    if len(line) < 3 or not line[:3].isdigit():
        raise NNTPProtocolError(f"invalid NNTP status line: {line!r}")
    return int(line[:3]), line[4:] if len(line) > 4 else ""


def _send(stream: BinaryIO, command: str) -> None:
    stream.write(command.encode("ascii") + b"\r\n")
    stream.flush()


def _read_multiline(stream: BinaryIO) -> list[str]:
    lines: list[str] = []
    total = 0
    while True:
        line = _readline(stream)
        total += len(line) + 2
        if total > MAX_MULTILINE_BYTES:
            raise NNTPProtocolError("multiline response exceeds safety limit")
        if line == ".":
            return lines
        if line.startswith(".."):
            line = line[1:]
        lines.append(line)


def _tls_details(sock: ssl.SSLSocket, mode: str) -> TLSObservation:
    cert = sock.getpeercert() or {}
    subject = ", ".join("=".join(item) for group in cert.get("subject", ()) for item in group)
    issuer = ", ".join("=".join(item) for group in cert.get("issuer", ()) for item in group)
    cipher = sock.cipher()
    return TLSObservation(
        enabled=True,
        mode=mode,
        protocol=sock.version(),
        cipher=cipher[0] if cipher else None,
        peer_subject=subject or None,
        peer_issuer=issuer or None,
        not_before=cert.get("notBefore"),
        not_after=cert.get("notAfter"),
    )


def probe(
    host: str,
    *,
    port: int = 119,
    implicit_tls: bool = False,
    starttls: bool = False,
    timeout: float = 10.0,
) -> ProbeObservation:
    if implicit_tls and starttls:
        raise ValueError("implicit_tls and starttls are mutually exclusive")

    observation = ProbeObservation(
        observed_at=datetime.now(UTC).isoformat(),
        host=host,
        port=port,
        transport="tls" if implicit_tls else "tcp",
    )

    raw_sock: socket.socket | ssl.SSLSocket | None = None
    stream: BinaryIO | None = None
    try:
        started = time.monotonic()
        raw_sock = socket.create_connection((host, port), timeout=timeout)
        raw_sock.settimeout(timeout)
        observation.connect_ms = round((time.monotonic() - started) * 1000, 3)

        context = ssl.create_default_context()
        if implicit_tls:
            raw_sock = context.wrap_socket(raw_sock, server_hostname=host)
            observation.tls = _tls_details(raw_sock, "implicit")

        stream = raw_sock.makefile("rwb", buffering=0)
        greeting = _readline(stream)
        code, _ = _parse_status(greeting)
        observation.greeting_code = code
        observation.greeting = greeting
        observation.posting_allowed = code == 200 if code in {200, 201} else None

        if code not in {200, 201}:
            raise NNTPProtocolError(f"unexpected greeting code {code}")

        if starttls:
            _send(stream, "STARTTLS")
            starttls_line = _readline(stream)
            starttls_code, _ = _parse_status(starttls_line)
            if starttls_code != 382:
                raise NNTPProtocolError(f"STARTTLS rejected: {starttls_line}")
            stream.close()
            stream = None
            raw_sock = context.wrap_socket(raw_sock, server_hostname=host)
            observation.transport = "starttls"
            observation.tls = _tls_details(raw_sock, "starttls")
            stream = raw_sock.makefile("rwb", buffering=0)

        _send(stream, "CAPABILITIES")
        cap_line = _readline(stream)
        cap_code, _ = _parse_status(cap_line)
        if cap_code == 101:
            observation.capabilities = _read_multiline(stream)

        _send(stream, "MODE READER")
        mode_line = _readline(stream)
        mode_code, _ = _parse_status(mode_line)
        observation.mode_reader_code = mode_code
        observation.mode_reader_response = mode_line

        try:
            _send(stream, "QUIT")
            _readline(stream)
        except (OSError, NNTPProtocolError):
            pass

    except (OSError, ssl.SSLError, NNTPProtocolError) as exc:
        observation.error = f"{type(exc).__name__}: {exc}"
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

    return observation
