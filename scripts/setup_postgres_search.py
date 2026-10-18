#!/usr/bin/env python3
"""Create PostgreSQL full-text indexes used by NewsIntel search predicates."""

import argparse
import os
import sys
from pathlib import Path

from sqlalchemy import create_engine, text

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


INDEX_STATEMENTS = [
    """
    CREATE INDEX IF NOT EXISTS ix_articles_effective_at
    ON articles ((coalesce(published_at, fetched_at, ingested_at)) DESC)
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_articles_search_fts
    ON articles
    USING gin (to_tsvector('simple'::regconfig, coalesce(search_text, '')))
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_entities_search_fts
    ON entities
    USING gin (to_tsvector('simple'::regconfig, coalesce(search_text, '')))
    """,
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Install PostgreSQL search indexes")
    parser.add_argument(
        "--database-url",
        default=os.getenv("DATABASE_URL", ""),
        help="Target PostgreSQL URL; defaults to DATABASE_URL",
    )
    args = parser.parse_args()

    if not args.database_url.startswith(("postgresql://", "postgresql+psycopg2://")):
        print("ERROR: --database-url must point to PostgreSQL.", file=sys.stderr)
        return 2

    engine = create_engine(args.database_url, pool_pre_ping=True)
    try:
        with engine.begin() as connection:
            for statement in INDEX_STATEMENTS:
                connection.execute(text(statement))
            connection.execute(text("ANALYZE articles"))
            connection.execute(text("ANALYZE entities"))
        print("PostgreSQL full-text indexes installed and analyzed.")
        return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
