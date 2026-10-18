#!/usr/bin/env python3
"""Plan or execute a database restore from a NewsIntel backup."""

import argparse
import shutil
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
    parser = argparse.ArgumentParser(description="Plan or execute a NewsIntel database restore")
    parser.add_argument("backup", help="Path to .db or .dump backup file")
    parser.add_argument("--execute", action="store_true", help="Actually perform the restore")
    parser.add_argument("--confirm", default="", help="Required with --execute: RESTORE")
    args = parser.parse_args()

    backup = Path(args.backup).resolve()
    if not backup.exists():
        print(f"ERROR: backup does not exist: {backup}", file=sys.stderr)
        return 1

    database_url = settings.database_url
    if database_url.startswith("sqlite:///"):
        target = Path(database_url.replace("sqlite:///", "", 1)).resolve()
        print("SQLite restore plan:")
        print("1. Stop the API and scheduler.")
        print(f"2. Copy {backup} over {target}.")
        print("3. Restart the API and run scripts/smoke_test.py.")
        if not args.execute:
            print("\nDry run only. Add --execute --confirm RESTORE to perform this local restore.")
            return 0
        if args.confirm != "RESTORE":
            print("ERROR: --execute requires --confirm RESTORE", file=sys.stderr)
            return 1
        if backup == target:
            print("ERROR: backup and target are the same path.", file=sys.stderr)
            return 1
        shutil.copy2(backup, target)
        print(f"Restored SQLite database: {target}")
        return 0

    if database_url.startswith((
        "postgresql://",
        "postgresql+psycopg2://",
        "postgresql+psycopg://",
        "postgres://",
    )):
        restore_url = database_url.replace(
            "postgresql+psycopg2://", "postgresql://", 1
        ).replace("postgresql+psycopg://", "postgresql://", 1)
        print("PostgreSQL restore plan:")
        print("1. Stop the API and scheduler.")
        print("2. Create a fresh backup before restoring.")
        print(f"3. Run: pg_restore --clean --if-exists --dbname {restore_url} {backup}")
        print("4. Restart the API and run scripts/smoke_test.py.")
        if not args.execute:
            print("\nDry run only. Add --execute --confirm RESTORE to run pg_restore.")
            return 0
        if args.confirm != "RESTORE":
            print("ERROR: --execute requires --confirm RESTORE", file=sys.stderr)
            return 1
        pg_restore = find_postgres_tool("pg_restore")
        if pg_restore is None:
            print("ERROR: pg_restore could not be found.", file=sys.stderr)
            return 1
        subprocess.run([
            pg_restore,
            "--clean",
            "--if-exists",
            "--dbname",
            restore_url,
            str(backup),
        ], check=True)
        print("PostgreSQL restore completed.")
        return 0

    print(f"ERROR: unsupported DATABASE_URL scheme: {database_url}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
