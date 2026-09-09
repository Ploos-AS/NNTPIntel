from __future__ import annotations

from datetime import UTC, datetime

from nntpintel.storage import Storage


def normalize_message_id(message_id: str) -> str:
    value = message_id.strip()
    if len(value) < 3 or not value.startswith("<") or not value.endswith(">"):
        raise ValueError("Message-ID must be enclosed in angle brackets")
    if any(char.isspace() for char in value):
        raise ValueError("Message-ID must not contain whitespace")
    return value


def register_article(
    storage: Storage,
    message_id: str,
    *,
    newsgroup: str | None = None,
    article_date: str | None = None,
) -> int:
    message_id = normalize_message_id(message_id)
    group = newsgroup.strip() if newsgroup else None
    if group == "":
        group = None
    with storage.connect() as conn:
        conn.execute(
            """
            INSERT INTO propagation_articles(message_id, newsgroup, article_date)
            VALUES (?, ?, ?)
            ON CONFLICT(message_id) DO UPDATE SET
                newsgroup = COALESCE(excluded.newsgroup, propagation_articles.newsgroup),
                article_date = COALESCE(excluded.article_date, propagation_articles.article_date)
            """,
            (message_id, group, article_date),
        )
        article_id = int(
            conn.execute(
                "SELECT id FROM propagation_articles WHERE message_id = ?",
                (message_id,),
            ).fetchone()["id"]
        )
        conn.commit()
    return article_id


def record_presence(
    storage: Storage,
    message_id: str,
    endpoint_id: int,
    *,
    observed_at: str | None = None,
    present: bool,
    method: str = "stat",
    response_code: int | None = None,
    error: str | None = None,
) -> int:
    if method not in {"stat", "head"}:
        raise ValueError("propagation method must be 'stat' or 'head'")
    article_id = register_article(storage, message_id)
    timestamp = observed_at or datetime.now(UTC).isoformat()
    with storage.connect() as conn:
        endpoint = conn.execute("SELECT id FROM endpoints WHERE id = ?", (endpoint_id,)).fetchone()
        if endpoint is None:
            raise ValueError(f"unknown endpoint: {endpoint_id}")
        cursor = conn.execute(
            """
            INSERT INTO propagation_observations(
                article_id, endpoint_id, observed_at, present, method, response_code, error
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                article_id,
                endpoint_id,
                timestamp,
                int(present),
                method,
                response_code,
                error,
            ),
        )
        conn.commit()
        return int(cursor.lastrowid)


def propagation_summary(storage: Storage, message_id: str) -> dict:
    message_id = normalize_message_id(message_id)
    with storage.connect() as conn:
        article = conn.execute(
            """
            SELECT id, message_id, newsgroup, article_date, first_registered_at
            FROM propagation_articles
            WHERE message_id = ?
            """,
            (message_id,),
        ).fetchone()
        if article is None:
            raise ValueError(f"unknown propagation article: {message_id}")
        rows = conn.execute(
            """
            SELECT po.endpoint_id, s.host, e.port, e.transport, e.starttls,
                   MIN(po.observed_at) AS first_seen_at
            FROM propagation_observations po
            JOIN endpoints e ON e.id = po.endpoint_id
            JOIN servers s ON s.id = e.server_id
            WHERE po.article_id = ? AND po.present = 1
            GROUP BY po.endpoint_id
            ORDER BY first_seen_at ASC, po.endpoint_id ASC
            """,
            (article["id"],),
        ).fetchall()
        observation_count = int(
            conn.execute(
                "SELECT COUNT(*) FROM propagation_observations WHERE article_id = ?",
                (article["id"],),
            ).fetchone()[0]
        )

    baseline = datetime.fromisoformat(rows[0]["first_seen_at"]) if rows else None
    endpoints: list[dict] = []
    for row in rows:
        first_seen = datetime.fromisoformat(row["first_seen_at"])
        delay_seconds = (first_seen - baseline).total_seconds() if baseline is not None else 0.0
        endpoints.append(
            {
                "endpoint_id": int(row["endpoint_id"]),
                "host": row["host"],
                "port": int(row["port"]),
                "transport": row["transport"],
                "starttls": bool(row["starttls"]),
                "first_seen_at": row["first_seen_at"],
                "delay_seconds": round(delay_seconds, 3),
            }
        )

    return {
        "article_id": int(article["id"]),
        "message_id": article["message_id"],
        "newsgroup": article["newsgroup"],
        "article_date": article["article_date"],
        "first_registered_at": article["first_registered_at"],
        "observation_count": observation_count,
        "visible_endpoint_count": len(endpoints),
        "first_visibility_at": rows[0]["first_seen_at"] if rows else None,
        "endpoints": endpoints,
    }
