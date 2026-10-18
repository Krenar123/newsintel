#!/usr/bin/env python3
"""Copy a NewsIntel SQLite database into an empty PostgreSQL rehearsal database."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import create_engine, func, select, text

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings
from src.models.database import Base, create_all_tables


SKIP_TABLES = {"auth_tokens", "client_dashboard_cache"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate SQLite data to PostgreSQL")
    parser.add_argument("--source-url", default=settings.database_url)
    parser.add_argument(
        "--target-url",
        default=os.getenv("POSTGRES_REHEARSAL_URL", ""),
        help="PostgreSQL URL; may also be set with POSTGRES_REHEARSAL_URL",
    )
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", default="")
    parser.add_argument("--reset-target", action="store_true")
    parser.add_argument("--allow-remote", action="store_true")
    args = parser.parse_args()

    if not args.source_url.startswith("sqlite"):
        print("ERROR: source URL must be SQLite.", file=sys.stderr)
        return 2
    if not args.target_url.startswith(("postgresql://", "postgresql+psycopg2://")):
        print("ERROR: target URL must be PostgreSQL.", file=sys.stderr)
        return 2

    parsed = urlparse(args.target_url.replace("postgresql+psycopg2://", "postgresql://"))
    if not args.allow_remote and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        print("ERROR: remote targets require --allow-remote.", file=sys.stderr)
        return 2

    source_engine = create_engine(args.source_url)
    target_engine = create_engine(args.target_url, pool_pre_ping=True)
    try:
        source_counts = _table_counts(source_engine)
        print(f"Source tables: {len(source_counts)}")
        print(f"Source rows: {sum(source_counts.values()):,}")
        for name, count in sorted(source_counts.items()):
            if count:
                print(f"  {name}: {count:,}")

        if not args.apply:
            print("\nDry run only. Use --apply --confirm MIGRATE_NEWSINTEL to copy data.")
            return 0
        if args.confirm != "MIGRATE_NEWSINTEL":
            print("ERROR: --confirm MIGRATE_NEWSINTEL is required.", file=sys.stderr)
            return 2

        create_all_tables(target_engine)
        if args.reset_target:
            _truncate_target(target_engine)

        with source_engine.connect() as source:
            for table in Base.metadata.sorted_tables:
                if table.name in SKIP_TABLES:
                    print(f"Skip {table.name}")
                    continue
                expected = source_counts.get(table.name, 0)
                if not expected:
                    continue
                existing = _count_table(target_engine, table.name)
                if existing:
                    raise RuntimeError(
                        f"Target table {table.name} is not empty ({existing} rows). "
                        "Use a new database or --reset-target."
                    )
                copied = 0
                result = source.execute(select(table)).mappings()
                while True:
                    rows = result.fetchmany(max(50, args.batch_size))
                    if not rows:
                        break
                    payload = [_sanitize_row(dict(row), table) for row in rows]
                    with target_engine.begin() as target:
                        target.execute(table.insert(), payload)
                    copied += len(payload)
                    print(f"\r{table.name}: {copied:,}/{expected:,}", end="", flush=True)
                print()
                _reset_sequence(target_engine, table.name)

        target_counts = _table_counts(target_engine)
        mismatches = {
            name: (count, target_counts.get(name, 0))
            for name, count in source_counts.items()
            if name not in SKIP_TABLES and count != target_counts.get(name, 0)
        }
        if mismatches:
            print(f"ERROR: count mismatches: {mismatches}", file=sys.stderr)
            return 1
        print("Migration completed with matching table counts.")
        return 0
    finally:
        source_engine.dispose()
        target_engine.dispose()


def _table_counts(engine) -> dict[str, int]:
    inspector_names = set()
    from sqlalchemy import inspect
    inspector_names.update(inspect(engine).get_table_names())
    counts = {}
    with engine.connect() as connection:
        for table in Base.metadata.sorted_tables:
            if table.name in inspector_names:
                counts[table.name] = int(
                    connection.execute(select(func.count()).select_from(table)).scalar() or 0
                )
    return counts


def _count_table(engine, table_name: str) -> int:
    with engine.connect() as connection:
        return int(connection.execute(
            text(f'SELECT count(*) FROM "{table_name}"')
        ).scalar() or 0)


def _truncate_target(engine) -> None:
    names = [
        table.name for table in reversed(Base.metadata.sorted_tables)
        if table.name not in SKIP_TABLES
    ]
    if not names:
        return
    quoted = ", ".join(f'"{name}"' for name in names)
    with engine.begin() as connection:
        connection.execute(text(f"TRUNCATE TABLE {quoted} RESTART IDENTITY CASCADE"))
    print("Target tables reset.")


def _reset_sequence(engine, table_name: str) -> None:
    # pg_get_serial_sequence may be null for tables without an integer identity.
    with engine.begin() as connection:
        sequence = connection.execute(
            text("SELECT pg_get_serial_sequence(:table_name, 'id')"),
            {"table_name": table_name},
        ).scalar()
        if not sequence:
            return
        maximum = connection.execute(
            text(f'SELECT COALESCE(max(id), 0) FROM "{table_name}"')
        ).scalar()
        if maximum:
            connection.execute(
                text("SELECT setval(:sequence, :maximum, true)"),
                {"sequence": sequence, "maximum": int(maximum)},
            )


def _sanitize_row(row: dict, table) -> dict:
    """Remove invalid bytes and enforce model-declared string lengths."""
    cleaned = {key: _sanitize_value(value) for key, value in row.items()}
    for column in table.columns:
        length = getattr(column.type, "length", None)
        value = cleaned.get(column.name)
        if length and isinstance(value, str) and len(value) > length:
            cleaned[column.name] = value[:length]
    return cleaned


def _sanitize_value(value):
    if isinstance(value, str):
        return value.replace("\x00", "")
    if isinstance(value, dict):
        return {key: _sanitize_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_sanitize_value(item) for item in value)
    return value


if __name__ == "__main__":
    raise SystemExit(main())
