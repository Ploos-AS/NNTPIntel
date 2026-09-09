# ruff: noqa: I001
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from urllib import parse

from nntpintel.storage import Storage


DISCOVERY_SQL = """
CREATE TABLE IF NOT EXISTS discovery_sources (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    source_ref TEXT,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_import_at TEXT
);

CREATE TABLE IF NOT EXISTS server_sources (
    server_id INTEGER NOT NULL REFERENCES servers(id) ON DELETE CASCADE,
    source_id INTEGER NOT NULL REFERENCES discovery_sources(id) ON DELETE CASCADE,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    PRIMARY KEY(server_id, source_id)
);
"""


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
        conn.executescript(DISCOVERY_SQL)
        conn.commit()


def import_seeds(
    storage: Storage,
    seeds: list[str],
    *,
    source: str,
    source_ref: str | None = None,
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
        conn.commit()

    imported = 0
    for seed in unique:
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
            conn.execute(
                """
                INSERT INTO server_sources(server_id, source_id, first_seen_at, last_seen_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(server_id, source_id) DO UPDATE SET last_seen_at = excluded.last_seen_at
                """,
                (server_id, source_id, now, now),
            )
            conn.commit()
        imported += 1

    return {"accepted": len(unique), "imported": imported, "rejected": rejected}


def list_sources(storage: Storage) -> list[dict]:
    ensure_discovery_schema(storage)
    with storage.connect() as conn:
        rows = conn.execute(
            """
            SELECT ds.id, ds.name, ds.source_ref, ds.enabled, ds.created_at, ds.last_import_at,
                   COUNT(ss.server_id) AS server_count
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
