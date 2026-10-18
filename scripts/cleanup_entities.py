#!/usr/bin/env python3
"""
Review and clean low-quality extracted entities.

Default mode is dry-run:
    python scripts/cleanup_entities.py --limit 200

Apply safe changes:
    python scripts/cleanup_entities.py --apply --limit 200
"""

import argparse
import datetime
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import settings
from src.models.database import (
    Article,
    Entity,
    EntityMention,
    EntityStatus,
    EntityType,
    create_all_tables,
    get_engine,
    get_session_factory,
)
from src.processing.entities import (
    EntityExtractor,
    corrected_entity_type,
    is_likely_entity_name,
)
from src.processing.entity_registry import alias_value


def main():
    parser = argparse.ArgumentParser(description="Clean and review entity quality")
    parser.add_argument("--apply", action="store_true", help="Write changes to the database")
    parser.add_argument("--limit", type=int, default=200, help="Maximum entities to inspect")
    parser.add_argument(
        "--include-approved",
        action="store_true",
        help="Also inspect manually approved entities",
    )
    parser.add_argument(
        "--delete-hidden",
        action="store_true",
        help="Delete entities that are already hidden and have no mentions",
    )
    args = parser.parse_args()

    engine = get_engine(settings.database_url)
    create_all_tables(engine)
    Session = get_session_factory(engine)
    session = Session()
    curated_types = _load_curated_types()

    try:
        query = session.query(Entity).order_by(Entity.total_mentions.desc(), Entity.name.asc())
        if not args.include_approved:
            excluded_statuses = [EntityStatus.APPROVED]
            if not args.delete_hidden:
                excluded_statuses.append(EntityStatus.HIDDEN)
            query = query.filter(Entity.status.notin_(excluded_statuses))
        entities = query.limit(args.limit).all()

        hide = []
        type_updates = []
        delete = []

        for entity in entities:
            current_type = entity.entity_type.value
            canonical = EntityExtractor._canonicalize(entity.name)
            corrected_type = curated_types.get(
                canonical,
                corrected_entity_type(entity.name, current_type),
            )
            if corrected_type == "person" and curated_types.get(canonical) != "person":
                corrected_type = current_type
            likely = is_likely_entity_name(entity.name, current_type)

            if not likely and entity.status != EntityStatus.APPROVED:
                hide.append(entity)
            elif corrected_type != current_type:
                type_updates.append((entity, corrected_type))

            if (
                args.delete_hidden
                and entity.status == EntityStatus.HIDDEN
                and not entity.mentions
            ):
                delete.append(entity)

        print(f"Inspected: {len(entities)}")
        print(f"Would hide: {len(hide)}")
        print(f"Would correct type: {len(type_updates)}")
        print(f"Would delete empty hidden: {len(delete)}")

        if hide:
            print("\nHide candidates:")
            for entity in hide[:40]:
                print(_safe(f"  #{entity.id} {entity.name} [{entity.entity_type.value}] mentions={entity.total_mentions}"))

        if type_updates:
            print("\nType corrections:")
            for entity, next_type in type_updates[:40]:
                print(_safe(f"  #{entity.id} {entity.name}: {entity.entity_type.value} -> {next_type}"))

        if not args.apply:
            print("\nDry run only. Add --apply to write these safe changes.")
            return

        now = datetime.datetime.utcnow()
        for entity in hide:
            entity.status = EntityStatus.HIDDEN
            entity.review_notes = "Auto-hidden by entity cleanup quality filter"
            entity.reviewed_at = now

        for entity, next_type in type_updates:
            target_type = EntityType(next_type)
            conflict = (
                session.query(Entity)
                .filter(
                    Entity.id != entity.id,
                    Entity.canonical_name == entity.canonical_name,
                    Entity.entity_type == target_type,
                )
                .first()
            )
            if conflict:
                _merge_entities(session, source=entity, target=conflict)
            else:
                entity.entity_type = target_type
                entity.review_notes = "Auto-corrected entity type by cleanup"
                entity.reviewed_at = now

        for entity in delete:
            session.delete(entity)

        session.commit()
        print("\nApplied changes.")
    finally:
        session.close()
        engine.dispose()


def _load_curated_types() -> dict[str, str]:
    """Map canonical names and aliases to types trusted for automatic repair."""
    path = Path(__file__).resolve().parent.parent / "config" / "entities" / "north_macedonia.yaml"
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    result = {}
    for item in data.get("entities", []):
        entity_type = str(item.get("type", "")).strip()
        values = [item.get("name", ""), *(item.get("aliases", []) or [])]
        for raw_value in values:
            canonical = EntityExtractor._canonicalize(alias_value(raw_value))
            if canonical:
                result[canonical] = entity_type
    return result


def _merge_entities(session, source: Entity, target: Entity):
    mentions = (
        session.query(EntityMention)
        .filter(EntityMention.entity_id == source.id)
        .all()
    )
    for mention in mentions:
        existing = (
            session.query(EntityMention)
            .filter(
                EntityMention.entity_id == target.id,
                EntityMention.article_id == mention.article_id,
            )
            .first()
        )
        if existing:
            existing.mention_count += mention.mention_count
            if not existing.context_snippet:
                existing.context_snippet = mention.context_snippet
            session.delete(mention)
        else:
            mention.entity_id = target.id

    target.total_mentions = int(sum(m.mention_count for m in target.mentions))
    last_seen = (
        session.query(Article.published_at)
        .join(EntityMention, EntityMention.article_id == Article.id)
        .filter(EntityMention.entity_id == target.id)
        .order_by(Article.published_at.desc())
        .first()
    )
    if last_seen and last_seen[0]:
        target.last_seen_at = last_seen[0]

    source.status = EntityStatus.HIDDEN
    source.review_notes = f"Auto-merged into entity #{target.id}: {target.name}"
    source.reviewed_at = datetime.datetime.utcnow()
    source.total_mentions = 0


def _safe(value: str) -> str:
    return value.encode(sys.stdout.encoding or "utf-8", errors="replace").decode(
        sys.stdout.encoding or "utf-8"
    )


if __name__ == "__main__":
    main()
