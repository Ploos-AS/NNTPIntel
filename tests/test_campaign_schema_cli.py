import sqlite3

from nntpintel.admin import build_parser
from nntpintel.propagation_campaigns import get_campaign
from nntpintel.storage import SCHEMA_VERSION, Storage


def test_schema_v5_campaign_data_migrates_to_v6(tmp_path):
    path = tmp_path / "legacy-v5.db"
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            PRAGMA foreign_keys = ON;
            CREATE TABLE schema_version (version INTEGER NOT NULL);
            INSERT INTO schema_version(version) VALUES (5);
            CREATE TABLE servers (
                id INTEGER PRIMARY KEY,
                host TEXT NOT NULL UNIQUE,
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE endpoints (
                id INTEGER PRIMARY KEY,
                server_id INTEGER NOT NULL REFERENCES servers(id) ON DELETE CASCADE,
                port INTEGER NOT NULL,
                transport TEXT NOT NULL,
                starttls INTEGER NOT NULL DEFAULT 0,
                interval_seconds INTEGER NOT NULL DEFAULT 900,
                timeout_seconds REAL NOT NULL DEFAULT 10.0,
                enabled INTEGER NOT NULL DEFAULT 1,
                consecutive_failures INTEGER NOT NULL DEFAULT 0,
                next_probe_at TEXT,
                last_probe_at TEXT,
                UNIQUE(server_id, port, transport, starttls)
            );
            CREATE TABLE propagation_articles (
                id INTEGER PRIMARY KEY,
                message_id TEXT NOT NULL UNIQUE,
                newsgroup TEXT,
                article_date TEXT,
                first_registered_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE propagation_campaigns (
                id INTEGER PRIMARY KEY,
                article_id INTEGER NOT NULL REFERENCES propagation_articles(id) ON DELETE CASCADE,
                status TEXT NOT NULL DEFAULT 'active',
                interval_seconds INTEGER NOT NULL DEFAULT 300,
                timeout_seconds REAL NOT NULL DEFAULT 5.0,
                max_backoff_seconds INTEGER NOT NULL DEFAULT 21600,
                stop_after_visible INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                completed_at TEXT,
                UNIQUE(article_id, status)
            );
            CREATE TABLE propagation_campaign_endpoints (
                campaign_id INTEGER NOT NULL REFERENCES propagation_campaigns(id) ON DELETE CASCADE,
                endpoint_id INTEGER NOT NULL REFERENCES endpoints(id) ON DELETE CASCADE,
                PRIMARY KEY(campaign_id, endpoint_id)
            );
            INSERT INTO servers(id, host) VALUES (1, 'news.example.test');
            INSERT INTO endpoints(id, server_id, port, transport, starttls)
            VALUES (1, 1, 119, 'tcp', 0);
            INSERT INTO propagation_articles(id, message_id)
            VALUES (1, '<legacy@example.test>');
            INSERT INTO propagation_campaigns(
                id, article_id, status, interval_seconds, timeout_seconds,
                max_backoff_seconds, stop_after_visible, created_at, expires_at
            ) VALUES (
                1, 1, 'active', 300, 5.0, 21600, 1,
                '2026-09-09T04:00:00+00:00', '2026-09-10T04:00:00+00:00'
            );
            INSERT INTO propagation_campaign_endpoints(campaign_id, endpoint_id)
            VALUES (1, 1);
            """
        )
        conn.commit()

    storage = Storage(path)
    with storage.connect() as conn:
        version = int(conn.execute("SELECT version FROM schema_version").fetchone()["version"])
    assert version == SCHEMA_VERSION == 6
    campaign = get_campaign(storage, 1)
    assert campaign["message_id"] == "<legacy@example.test>"
    assert campaign["endpoint_ids"] == [1]
    assert campaign["status"] == "active"


def test_campaign_cli_commands_parse():
    parser = build_parser()

    create = parser.parse_args(
        [
            "create-propagation-campaign",
            "<cli@example.test>",
            "1",
            "2",
            "--interval",
            "120",
            "--ttl",
            "600",
            "--stop-after-visible",
            "1",
        ]
    )
    assert create.command == "create-propagation-campaign"
    assert create.endpoint_ids == [1, 2]
    assert create.interval == 120
    assert create.ttl == 600
    assert create.stop_after_visible == 1

    listing = parser.parse_args(["list-propagation-campaigns", "--status", "active"])
    assert listing.command == "list-propagation-campaigns"
    assert listing.status == "active"

    state = parser.parse_args(["set-propagation-campaign-enabled", "7", "off"])
    assert state.campaign_id == 7
    assert state.state == "off"

    run = parser.parse_args(["run-propagation-campaign", "7"])
    assert run.campaign_id == 7

    due = parser.parse_args(["run-due-propagation-campaigns", "--limit", "2"])
    assert due.limit == 2
