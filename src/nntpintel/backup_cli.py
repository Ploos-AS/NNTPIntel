from __future__ import annotations

import argparse
import json
import os
import pathlib
from collections.abc import Sequence

from nntpintel.backup import create_backup, restore_backup, verify_backup


def _database_url(value: str | None, *, env_name: str = "NNTPINTEL_DATABASE_URL") -> str:
    result = value or os.environ.get(env_name)
    if not result:
        raise SystemExit(f"PostgreSQL URL required via --database-url or {env_name}")
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="nntpintel-backup")
    sub = parser.add_subparsers(dest="command", required=True)

    backup = sub.add_parser("backup", help="create a PostgreSQL custom-format backup")
    backup.add_argument("output", type=pathlib.Path)
    backup.add_argument("--database-url")
    backup.add_argument("--force", action="store_true", help="overwrite an existing backup")

    verify = sub.add_parser("verify", help="verify checksum and pg_restore readability")
    verify.add_argument("backup", type=pathlib.Path)

    restore = sub.add_parser("restore", help="restore a verified backup into a target database")
    restore.add_argument("backup", type=pathlib.Path)
    restore.add_argument("--database-url", help="target PostgreSQL URL")
    restore.add_argument("--clean", action="store_true", help="drop matching objects before restore")
    restore.add_argument("--yes", action="store_true", help="confirm destructive restore")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "backup":
        manifest = create_backup(
            _database_url(args.database_url),
            args.output,
            overwrite=args.force,
        )
        print(json.dumps(manifest.as_dict(), sort_keys=True))
        return 0

    if args.command == "verify":
        manifest = verify_backup(args.backup)
        print(json.dumps({"verified": True, **manifest.as_dict()}, sort_keys=True))
        return 0

    if args.command == "restore":
        if not args.yes:
            manifest = verify_backup(args.backup)
            print(
                json.dumps(
                    {
                        "dry_run": True,
                        "verified": True,
                        "clean": bool(args.clean),
                        **manifest.as_dict(),
                    },
                    sort_keys=True,
                )
            )
            return 0
        manifest = restore_backup(
            _database_url(args.database_url),
            args.backup,
            clean=args.clean,
        )
        print(json.dumps({"restored": True, **manifest.as_dict()}, sort_keys=True))
        return 0

    raise AssertionError("unreachable")


if __name__ == "__main__":
    raise SystemExit(main())
