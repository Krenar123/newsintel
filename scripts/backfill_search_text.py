#!/usr/bin/env python3
"""Backfill Cyrillic/Latin normalized search blobs for existing data."""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import settings
from src.models.database import (
    Article,
    Entity,
    create_all_tables,
    get_engine,
    get_session_factory,
)
from src.search.normalization import search_blob


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill normalized search text")
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--force", action="store_true", help="Rebuild existing search blobs")
    args = parser.parse_args()

    engine = get_engine(settings.database_url)
    create_all_tables(engine)
    session_factory = get_session_factory(engine)
    session = session_factory()

    article_query = session.query(Article)
    entity_query = session.query(Entity)
    if not args.force:
        article_query = article_query.filter(Article.search_text == None)
        entity_query = entity_query.filter(Entity.search_text == None)

    article_count = 0
    for article in article_query.yield_per(args.batch_size):
        article.search_text = search_blob(article.title, article.content, article.author)
        article_count += 1
        if article_count % args.batch_size == 0:
            session.commit()

    entity_count = 0
    for entity in entity_query.yield_per(args.batch_size):
        entity.search_text = search_blob(entity.name, entity.canonical_name)
        entity_count += 1
        if entity_count % args.batch_size == 0:
            session.commit()

    session.commit()
    session.close()
    print(f"Backfilled search text: {article_count} articles, {entity_count} entities")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
