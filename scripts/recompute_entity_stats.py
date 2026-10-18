#!/usr/bin/env python3
"""Reconcile cached entity mention totals and last-seen timestamps."""

import argparse
import sys
from pathlib import Path

from sqlalchemy import func

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import settings
from src.models.database import (
    Article,
    Entity,
    EntityMention,
    create_all_tables,
    get_engine,
    get_session_factory,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Recompute entity statistics from mention rows")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    engine = get_engine(settings.database_url)
    create_all_tables(engine)
    session = get_session_factory(engine)()
    try:
        grouped = {
            entity_id: (int(total or 0), last_seen)
            for entity_id, total, last_seen in (
                session.query(
                    EntityMention.entity_id,
                    func.sum(EntityMention.mention_count),
                    func.max(func.coalesce(Article.published_at, Article.fetched_at)),
                )
                .join(Article, Article.id == EntityMention.article_id)
                .group_by(EntityMention.entity_id)
                .all()
            )
        }
        changed = 0
        zero_mention_entities = 0
        for entity in session.query(Entity).all():
            total, last_seen = grouped.get(entity.id, (0, None))
            zero_mention_entities += int(total == 0)
            if entity.total_mentions != total or (last_seen and entity.last_seen_at != last_seen):
                changed += 1
            if args.apply:
                entity.total_mentions = total
                if last_seen is not None:
                    entity.last_seen_at = last_seen

        if args.apply:
            session.commit()
        print(f"Entities checked: {session.query(Entity).count()}")
        print(f"Rows requiring reconciliation: {changed}")
        print(f"Entities with zero active mentions: {zero_mention_entities}")
        print("Applied changes." if args.apply else "Dry run only. Add --apply to write changes.")
        return 0
    finally:
        session.close()
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
