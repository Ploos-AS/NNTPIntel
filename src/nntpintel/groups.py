from __future__ import annotations

import socket
import ssl
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import BinaryIO

from nntpintel.probe import NNTPProtocolError, _parse_status, _read_multiline, _readline, _send


@dataclass(slots=True)
class GroupRecord:
    name: str
    high: int | None = None
    low: int | None = None
    status: str | None = None
    description: str | None = None

    @property
    def hierarchy(self) -> str:
        return self.name.split(".", 1)[0]


@dataclass(slots=True)
class GroupInventory:
    observed_at: str
    host: str
    port: int
    transport: str
    groups: list[GroupRecord] = field(default_factory=list)
    error: str | None = None


def _parse_active(lines: list[str]) -> dict[str, GroupRecord]:
    result: dict[str, GroupRecord] = {}
    for line in lines:
        parts = line.split()
        if len(parts) < 4:
            continue
        name, high_text, low_text, status = parts[:4]
        try:
            high = int(high_text)
            low = int(low_text)
        except ValueError:
            high = None
            low = None
        result[name] = GroupRecord(name=name, high=high, low=low, status=status)
    return result


def _apply_descriptions(groups: dict[str, GroupRecord], lines: list[str]) -> None:
    for line in lines:
        name, separator, description = line.partition(" ")
        if not separator:
            continue
        record = groups.get(name)
        if record is not None:
            record.description = description.strip() or None


def _command_multiline(stream: BinaryIO, command: str, expected: set[int]) -> list[str]:
    _send(stream, command)
    response = _readline(stream)
    code, _ = _parse_status(response)
    if code not in expected:
        raise NNTPProtocolError(f"{command} rejected: {response}")
    return _read_multiline(stream)


def inventory_groups(
    host: str,
    *,
    port: int = 119,
    implicit_tls: bool = False,
    timeout: float = 10.0,
) -> GroupInventory:
    observation = GroupInventory(
        observed_at=datetime.now(UTC).isoformat(),
        host=host,
        port=port,
        transport="tls" if implicit_tls else "tcp",
    )
    sock: socket.socket | ssl.SSLSocket | None = None
    stream: BinaryIO | None = None
    try:
        sock = socket.create_connection((host, port), timeout=timeout)
        sock.settimeout(timeout)
        if implicit_tls:
            context = ssl.create_default_context()
            sock = context.wrap_socket(sock, server_hostname=host)
        stream = sock.makefile("rwb", buffering=0)

        greeting = _readline(stream)
        code, _ = _parse_status(greeting)
        if code not in {200, 201}:
            raise NNTPProtocolError(f"unexpected greeting code {code}")

        active = _command_multiline(stream, "LIST ACTIVE", {215})
        groups = _parse_active(active)

        try:
            descriptions = _command_multiline(stream, "LIST NEWSGROUPS", {215})
        except NNTPProtocolError:
            descriptions = []
        _apply_descriptions(groups, descriptions)
        observation.groups = sorted(groups.values(), key=lambda item: item.name)

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
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass
    return observation
