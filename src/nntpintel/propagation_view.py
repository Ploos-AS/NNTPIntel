from __future__ import annotations

from nntpintel.propagation import propagation_summary
from nntpintel.propagation_campaigns import list_campaigns
from nntpintel.storage import Storage


def propagation_overview(storage: Storage) -> dict:
    with storage.connect() as conn:
        row = conn.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM propagation_articles) AS article_count,
                (SELECT COUNT(*) FROM propagation_campaigns WHERE status = 'active') AS active_campaign_count,
                (SELECT COUNT(DISTINCT endpoint_id) FROM propagation_observations) AS measured_endpoint_count,
                (SELECT COUNT(*) FROM propagation_observations) AS observation_count
            """
        ).fetchone()
    return {
        "article_count": int(row["article_count"]),
        "active_campaign_count": int(row["active_campaign_count"]),
        "measured_endpoint_count": int(row["measured_endpoint_count"]),
        "observation_count": int(row["observation_count"]),
    }


def list_propagation_articles(storage: Storage, *, limit: int = 100) -> list[dict]:
    if limit < 1 or limit > 1000:
        raise ValueError("propagation article limit must be between 1 and 1000")
    with storage.connect() as conn:
        rows = conn.execute(
            """
            SELECT pa.id, pa.message_id, pa.newsgroup, pa.article_date, pa.first_registered_at,
                   COUNT(po.id) AS observation_count,
                   COUNT(DISTINCT CASE
                       WHEN po.present = 1 AND po.error IS NULL AND po.response_code = 223
                       THEN po.endpoint_id END) AS visible_endpoint_count,
                   MIN(CASE
                       WHEN po.present = 1 AND po.error IS NULL AND po.response_code = 223
                       THEN po.observed_at END) AS first_visibility_at
            FROM propagation_articles pa
            LEFT JOIN propagation_observations po ON po.article_id = pa.id
            GROUP BY pa.id
            ORDER BY pa.first_registered_at DESC, pa.id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def propagation_observation_history(storage: Storage, article_id: int, *, limit: int = 500) -> list[dict]:
    if limit < 1 or limit > 5000:
        raise ValueError("propagation observation limit must be between 1 and 5000")
    with storage.connect() as conn:
        rows = conn.execute(
            """
            SELECT po.id, po.endpoint_id, s.host, e.port, e.transport, e.starttls,
                   po.observed_at, po.present, po.method, po.response_code, po.error
            FROM propagation_observations po
            JOIN endpoints e ON e.id = po.endpoint_id
            JOIN servers s ON s.id = e.server_id
            WHERE po.article_id = ?
            ORDER BY po.observed_at ASC, po.id ASC
            LIMIT ?
            """,
            (article_id, limit),
        ).fetchall()
    result: list[dict] = []
    for row in rows:
        item = dict(row)
        if item["error"] is not None:
            item["state"] = "unknown"
        elif item["response_code"] == 223 and item["present"]:
            item["state"] = "present"
        elif item["response_code"] == 430:
            item["state"] = "absent"
        else:
            item["state"] = "unknown"
        result.append(item)
    return result


def get_propagation_article(storage: Storage, article_id: int) -> dict | None:
    with storage.connect() as conn:
        row = conn.execute(
            "SELECT id, message_id FROM propagation_articles WHERE id = ?",
            (article_id,),
        ).fetchone()
    if row is None:
        return None

    result = propagation_summary(storage, str(row["message_id"]))
    result["observations"] = propagation_observation_history(storage, article_id)
    result["campaigns"] = [
        campaign for campaign in list_campaigns(storage, limit=1000) if int(campaign["article_id"]) == article_id
    ]
    return result


def list_propagation_campaigns(storage: Storage, *, limit: int = 100) -> list[dict]:
    return list_campaigns(storage, limit=limit)
