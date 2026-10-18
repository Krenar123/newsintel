#!/usr/bin/env python3
"""Create a timestamped database backup for SQLite or PostgreSQL."""

import argparse
import datetime
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import settings


def find_postgres_tool(name: str) -> str | None:
    """Find PostgreSQL client tools on PATH or in standard Windows installs."""
    on_path = shutil.which(name)
    if on_path:
        return on_path
    if sys.platform == "win32":
        program_files = Path("C:/Program Files/PostgreSQL")
        matches = sorted(
            program_files.glob(f"*/bin/{name}.exe"),
            reverse=True,
        )
        if matches:
            return str(matches[0])
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Back up the configured NewsIntel database")
    parser.add_argument("--output-dir", default=str(settings.base_dir / "data" / "backups"))
    parser.add_argument("--label", default="manual")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    stamp = datetime.datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    label = sanitize_label(args.label)
    database_url = settings.database_url

    if database_url.startswith("sqlite:///"):
        source = Path(database_url.replace("sqlite:///", "", 1))
        target = output_dir / f"newsintel-{label}-{stamp}.db"
        print(f"SQLite source: {source}")
        print(f"Backup target: {target}")
        if args.dry_run:
            return 0
        if not source.exists():
            print(f"ERROR: database file does not exist: {source}", file=sys.stderr)
            return 1
        output_dir.mkdir(parents=True, exist_ok=True)
        # SQLite's backup API creates a transactionally consistent snapshot
        # while ingestion/API processes may still have the database open.
        with sqlite3.connect(source) as source_db, sqlite3.connect(target) as target_db:
            source_db.backup(target_db)
        print(f"Backup created: {target}")
        return 0

    if database_url.startswith((
        "postgresql://",
        "postgresql+psycopg2://",
        "postgresql+psycopg://",
        "postgres://",
    )):
        target = output_dir / f"newsintel-{label}-{stamp}.dump"
        pg_dump = find_postgres_tool("pg_dump")
        dump_url = database_url.replace(
            "postgresql+psycopg2://", "postgresql://", 1
        ).replace("postgresql+psycopg://", "postgresql://", 1)
        command = [pg_dump or "pg_dump", "--format=custom", "--file", str(target), dump_url]
        print("PostgreSQL backup command:")
        print(" ".join(command))
        if args.dry_run:
            return 0
        if pg_dump is None:
            print("ERROR: pg_dump could not be found.", file=sys.stderr)
            return 1
        output_dir.mkdir(parents=True, exist_ok=True)
        subprocess.run(command, check=True)
        print(f"Backup created: {target}")
        return 0

    print(f"ERROR: unsupported DATABASE_URL scheme: {database_url}", file=sys.stderr)
    return 1


def sanitize_label(value: str) -> str:
    cleaned = "".join(char if char.isalnum() or char in {"-", "_"} else "-" for char in value.strip())
    return cleaned.strip("-_")[:40] or "manual"


if __name__ == "__main__":
    raise SystemExit(main())
