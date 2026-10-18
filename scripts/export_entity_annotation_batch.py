#!/usr/bin/env python3
"""Export a deterministic, article-level entity annotation batch from the DB."""

import argparse
import datetime
import hashlib
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config import settings
from src.models.database import (
    Article,
    Entity,
    EntityMention,
    EntityStatus,
    Source,
    create_all_tables,
    get_engine,
    get_session_factory,
)


def _split(article_id: int) -> str:
    bucket = int(hashlib.sha256(str(article_id).encode("ascii")).hexdigest()[:8], 16) % 5
    return "holdout" if bucket == 0 else "calibration"


def _select_stratified(groups: dict[tuple[str, str], list[dict]], limit: int, seed: int) -> list[dict]:
    rng = random.Random(seed)
    queues = []
    for key in sorted(groups):
        values = groups[key]
        rng.shuffle(values)
        queues.append(values)
    selected = []
    while queues and len(selected) < limit:
        next_round = []
        for queue in queues:
            if queue and len(selected) < limit:
                selected.append(queue.pop())
            if queue:
                next_round.append(queue)
        queues = next_round
    return selected


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--seed", type=int, default=20261018)
    parser.add_argument("--excerpt-chars", type=int, default=2500)
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="JSONL destination; defaults to data/entity_annotations/.",
    )
    args = parser.parse_args()
    if args.limit < 1 or args.excerpt_chars < 500:
        raise SystemExit("--limit must be positive and --excerpt-chars at least 500")

    engine = get_engine(settings.database_url)
    create_all_tables(engine)
    session = get_session_factory(engine)()
    try:
        rows = (
            session.query(EntityMention, Entity, Article, Source)
            .join(Entity, Entity.id == EntityMention.entity_id)
            .join(Article, Article.id == EntityMention.article_id)
            .outerjoin(Source, Source.id == Article.source_id)
            .filter(Entity.status.in_([EntityStatus.NEEDS_REVIEW, EntityStatus.APPROVED]))
            .order_by(Article.id.desc(), Entity.total_mentions.desc())
            .limit(max(args.limit * 40, args.limit))
            .all()
        )
        articles: dict[int, dict] = {}
        for mention, entity, article, source in rows:
            record = articles.setdefault(article.id, {
                "schema_version": 2,
                "record_id": f"article-{article.id}",
                "split": _split(article.id),
                "article_id": article.id,
                "title": article.title,
                "text": "\n".join(
                    part for part in (article.title, (article.content or "")[: args.excerpt_chars])
                    if part
                ),
                "language": article.language,
                "source": source.name if source else None,
                "published_at": article.published_at.isoformat() if article.published_at else None,
                "article_url": article.url,
                "candidates": [],
                "annotation": {
                    "gold_entities": None,
                    "reviewer": None,
                    "reviewed_at": None,
                    "notes": None,
                },
            })
            candidate = {
                "entity_id": entity.id,
                "name": entity.name,
                "type": entity.entity_type.value,
                "status": entity.status.value,
                "context": mention.context_snippet,
            }
            if candidate not in record["candidates"]:
                record["candidates"].append(candidate)

        grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
        for record in articles.values():
            grouped[(record["language"] or "unknown", record["source"] or "unknown")].append(record)
        selected = _select_stratified(grouped, args.limit, args.seed)

        output = args.output or (
            ROOT
            / "data"
            / "entity_annotations"
            / f"entity_batch_{datetime.datetime.utcnow():%Y%m%d_%H%M%S}.jsonl"
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("w", encoding="utf-8", newline="\n") as handle:
            for record in selected:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")

        split_counts = {
            split: sum(record["split"] == split for record in selected)
            for split in ("calibration", "holdout")
        }
        print(
            f"Exported {len(selected)} articles to {output} "
            f"(calibration={split_counts['calibration']}, holdout={split_counts['holdout']})"
        )
        return 0
    finally:
        session.close()
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
