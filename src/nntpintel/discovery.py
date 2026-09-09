# ruff: noqa: I001
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from html.parser import HTMLParser
from urllib import parse, request

from nntpintel.storage import SCHEMA_VERSION, Storage


MAX_SOURCE_BYTES = 1024 * 1024
BUILTIN_SOURCES = {
    "vivil-open-nntp": (
        "https://vivil.free.fr/nntpeng.htm",
        "open-nntp-html",
    ),
}


@dataclass(frozen=True)
class Seed:
    host: str
    port: int = 119
    transport: str = "tcp"
    starttls: bool = False


def _now() -> str:
    return datetime.now(UTC).isoformat()


def normalize_host(host: str) -> str:
    value = host.strip().rstrip(".").lower()
    if not value or any(char.isspace() for char in value):
        raise ValueError("invalid host")
    return value


def parse_seed(value: str) -> Seed:
    text = value.strip()
    if not text or text.startswith("#"):
        raise ValueError("empty seed")

    if "://" not in text:
        text = f"nntp://{text}"
    parsed = parse.urlparse(text)
    if parsed.scheme not in {"nntp", "nntps"} or not parsed.hostname:
        raise ValueError(f"unsupported seed: {value}")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment or parsed.username:
        raise ValueError(f"unsupported seed: {value}")

    implicit_tls = parsed.scheme == "nntps"
    return Seed(
        host=normalize_host(parsed.hostname),
        port=parsed.port or (563 if implicit_tls else 119),
        transport="tls" if implicit_tls else "tcp",
    )


def ensure_discovery_schema(storage: Storage) -> None:
    with storage.connect() as conn:
        row = conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
    if row is None or int(row["version"]) != SCHEMA_VERSION:
        raise RuntimeError("discovery schema requires initialized Storage schema")


def _server_id(storage: Storage, host: str) -> int | None:
    with storage.connect() as conn:
        row = conn.execute("SELECT id FROM servers WHERE host = ?", (host,)).fetchone()
        return None if row is None else int(row["id"])


def import_seeds(
    storage: Storage,
    seeds: list[str],
    *,
    source: str,
    source_ref: str | None = None,
    activate: bool = False,
    snapshot: bool = False,
) -> dict[str, int]:
    ensure_discovery_schema(storage)
    source_name = source.strip()
    if not source_name:
        raise ValueError("source name is required")

    parsed: list[Seed] = []
    rejected = 0
    for raw in seeds:
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        try:
            parsed.append(parse_seed(stripped))
        except (ValueError, TypeError):
            rejected += 1

    unique = list(dict.fromkeys(parsed))
    now = _now()
    with storage.connect() as conn:
        conn.execute(
            """
            INSERT INTO discovery_sources(name, source_ref, last_import_at)
            VALUES (?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                source_ref = COALESCE(excluded.source_ref, discovery_sources.source_ref),
                last_import_at = excluded.last_import_at
            """,
            (source_name, source_ref, now),
        )
        source_id = int(
            conn.execute("SELECT id FROM discovery_sources WHERE name = ?", (source_name,)).fetchone()["id"]
        )
        previous = {
            row["host"]
            for row in conn.execute(
                """
                SELECT s.host
                FROM server_sources ss
                JOIN servers s ON s.id = ss.server_id
                WHERE ss.source_id = ? AND ss.active = 1
                """,
                (source_id,),
            )
        }
        if snapshot:
            conn.execute("UPDATE server_sources SET active = 0 WHERE source_id = ?", (source_id,))
        conn.commit()

    imported = 0
    current_hosts: set[str] = set()
    for seed in unique:
        existed = _server_id(storage, seed.host) is not None
        endpoint_id = storage.ensure_endpoint(
            seed.host,
            port=seed.port,
            transport=seed.transport,
            starttls=seed.starttls,
        )
        with storage.connect() as conn:
            server_id = int(
                conn.execute("SELECT server_id FROM endpoints WHERE id = ?", (endpoint_id,)).fetchone()["server_id"]
            )
            if not existed and not activate:
                conn.execute("UPDATE servers SET enabled = 0 WHERE id = ?", (server_id,))
            conn.execute(
                """
                INSERT INTO server_sources(server_id, source_id, first_seen_at, last_seen_at, active)
                VALUES (?, ?, ?, ?, 1)
                ON CONFLICT(server_id, source_id) DO UPDATE SET
                    last_seen_at = excluded.last_seen_at,
                    active = 1
                """,
                (server_id, source_id, now, now),
            )
            conn.commit()
        current_hosts.add(seed.host)
        imported += 1

    added = len(current_hosts - previous)
    still_present = len(current_hosts & previous)
    missing = len(previous - current_hosts) if snapshot else 0
    return {
        "accepted": len(unique),
        "imported": imported,
        "rejected": rejected,
        "added": added,
        "still_present": still_present,
        "missing": missing,
    }


class _TextCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


_HOST_RE = re.compile(r"(?<![A-Za-z0-9.-])(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}(?![A-Za-z0-9.-])")


def extract_seeds(content: str, adapter: str) -> list[str]:
    if adapter == "text":
        return content.splitlines()
    if adapter == "open-nntp-html":
        parser = _TextCollector()
        parser.feed(content)
        hosts: list[str] = []
        for part in parser.parts:
            for host in _HOST_RE.findall(part):
                lowered = host.lower()
                if lowered.startswith(("news.", "nntp.")) or "usenet" in lowered:
                    hosts.append(lowered)
        return list(dict.fromkeys(hosts))
    raise ValueError(f"unknown discovery adapter: {adapter}")


def fetch_source(url: str, *, timeout: float = 15.0) -> str:
    parsed = parse.urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("discovery source must use http or https")
    req = request.Request(url, headers={"User-Agent": "NNTPIntel/0.1 discovery"})
    with request.urlopen(req, timeout=timeout) as response:
        data = response.read(MAX_SOURCE_BYTES + 1)
    if len(data) > MAX_SOURCE_BYTES:
        raise ValueError("discovery source exceeds size limit")
    return data.decode("utf-8", errors="replace")


def refresh_source(
    storage: Storage,
    *,
    source: str,
    source_ref: str,
    adapter: str,
    activate: bool = False,
    content: str | None = None,
) -> dict[str, int]:
    body = fetch_source(source_ref) if content is None else content
    seeds = extract_seeds(body, adapter)
    return import_seeds(
        storage,
        seeds,
        source=source,
        source_ref=source_ref,
        activate=activate,
        snapshot=True,
    )


def refresh_builtin_source(
    storage: Storage,
    name: str,
    *,
    activate: bool = False,
    content: str | None = None,
) -> dict[str, int]:
    try:
        source_ref, adapter = BUILTIN_SOURCES[name]
    except KeyError as exc:
        raise ValueError(f"unknown built-in source: {name}") from exc
    return refresh_source(
        storage,
        source=name,
        source_ref=source_ref,
        adapter=adapter,
        activate=activate,
        content=content,
    )


def list_sources(storage: Storage) -> list[dict]:
    ensure_discovery_schema(storage)
    with storage.connect() as conn:
        rows = conn.execute(
            """
            SELECT ds.id, ds.name, ds.source_ref, ds.enabled, ds.created_at, ds.last_import_at,
                   COUNT(ss.server_id) AS server_count,
                   COALESCE(SUM(CASE WHEN ss.active = 1 THEN 1 ELSE 0 END), 0) AS active_server_count
            FROM discovery_sources ds
            LEFT JOIN server_sources ss ON ss.source_id = ds.id
            GROUP BY ds.id
            ORDER BY ds.name
            """
        ).fetchall()
        return [dict(row) for row in rows]


def set_server_enabled(storage: Storage, host: str, enabled: bool) -> bool:
    normalized = normalize_host(host)
    with storage.connect() as conn:
        cursor = conn.execute(
            "UPDATE servers SET enabled = ? WHERE host = ?",
            (int(enabled), normalized),
        )
        conn.commit()
        return cursor.rowcount > 0
