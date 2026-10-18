#!/usr/bin/env python3
"""
Rebuild entity mentions for already stored articles using the latest extractor.

Dry-run:
    python scripts/reprocess_entities.py --limit 50

Apply:
    python scripts/reprocess_entities.py --apply --limit 500
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import settings
from src.models.database import (
    Article,
    Entity,
    EntityMention,
    EntityStatus,
    EntityType,
    Source,
    create_all_tables,
    get_engine,
    get_session_factory,
)
from src.processing.entities import EntityExtractor
from src.processing.entity_persistence import get_or_create_extracted_entity
from src.processing.sentiment import SentimentAnalyzer


def main():
    parser = argparse.ArgumentParser(description="Rebuild entity mentions with current extractor")
    parser.add_argument("--apply", action="store_true", help="Write rebuilt mentions")
    parser.add_argument("--limit", type=int, default=100, help="Number of articles to reprocess")
    parser.add_argument("--country", default="mk", help="Country code")
    parser.add_argument("--offset", type=int, default=0, help="Offset for batching")
    args = parser.parse_args()

    engine = get_engine(settings.database_url)
    create_all_tables(engine)
    Session = get_session_factory(engine)
    session = Session()

    extractor = EntityExtractor(languages=["mk", "en", "sq"])
    sentiment = SentimentAnalyzer()

    try:
        articles = (
            session.query(Article)
            .join(Source, Source.id == Article.source_id)
            .filter(Article.content != None)
            .filter(Article.content != "")
            .filter(Source.country_code == args.country)
            .order_by(Article.published_at.desc().nullslast(), Article.id.desc())
            .offset(args.offset)
            .limit(args.limit)
            .all()
        )
        total_mentions = 0
        touched_entities: set[int] = set()

        for article in articles:
            result = extractor.extract(article.content or "", language=article.language)
            total_mentions += len(result.entities)
            if not args.apply:
                continue

            old_mentions = (
                session.query(EntityMention)
                .filter(EntityMention.article_id == article.id)
                .all()
            )
            for mention in old_mentions:
                touched_entities.add(mention.entity_id)
                session.delete(mention)
            session.flush()

            for extracted in result.entities:
                entity = _get_or_create_entity(session, extracted)
                mention = EntityMention(
                    entity_id=entity.id,
                    article_id=article.id,
                    mention_count=extracted.mention_count,
                    context_snippet=extracted.context_snippets[0] if extracted.context_snippets else None,
                )
                if extracted.context_snippets:
                    mention.sentiment_score = sentiment.score_text(
                        " ".join(extracted.context_snippets),
                        language=article.language,
                    ).compound
                session.add(mention)
                touched_entities.add(entity.id)

            article.is_processed = True
            session.commit()

        if args.apply:
            for entity_id in touched_entities:
                _recompute_entity(session, entity_id)
            session.commit()

        print(f"Articles checked: {len(articles)}")
        print(f"Extracted mention rows: {total_mentions}")
        print("Applied changes." if args.apply else "Dry run only. Add --apply to rebuild mentions.")
    finally:
        session.close()
        engine.dispose()


def _get_or_create_entity(session, extracted) -> Entity:
    return get_or_create_extracted_entity(session, extracted)


def _recompute_entity(session, entity_id: int):
    entity = session.query(Entity).get(entity_id)
    if not entity:
        return
    mentions = (
        session.query(EntityMention)
        .filter(EntityMention.entity_id == entity_id)
        .all()
    )
    entity.total_mentions = sum(mention.mention_count for mention in mentions)
    article_dates = [
        mention.article.published_at or mention.article.fetched_at
        for mention in mentions
        if mention.article
    ]
    if article_dates:
        entity.last_seen_at = max(article_dates)


if __name__ == "__main__":
    main()
