#!/usr/bin/env python3
"""Approve curated entities and merge their stored aliases into canonical records."""

import argparse
import datetime
import sys
from pathlib import Path

import yaml
from sqlalchemy import func

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

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
from src.processing.entities import EntityExtractor
from src.processing.entity_registry import alias_value
from src.search.normalization import search_blob


def _merge(session, source: Entity, target: Entity) -> None:
    mentions = session.query(EntityMention).filter(EntityMention.entity_id == source.id).all()
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
            if existing.sentiment_score is None:
                existing.sentiment_score = mention.sentiment_score
            session.delete(mention)
        else:
            mention.entity_id = target.id
    source.status = EntityStatus.HIDDEN
    source.total_mentions = 0
    source.review_notes = f"Merged into curated entity #{target.id}: {target.name}"
    source.reviewed_at = datetime.datetime.utcnow()


def _refresh_totals(session, entity: Entity) -> None:
    total, first_seen, last_seen = (
        session.query(
            func.coalesce(func.sum(EntityMention.mention_count), 0),
            func.min(Article.published_at),
            func.max(Article.published_at),
        )
        .join(Article, Article.id == EntityMention.article_id)
        .filter(EntityMention.entity_id == entity.id)
        .one()
    )
    entity.total_mentions = int(total or 0)
    if first_seen:
        entity.first_seen_at = first_seen
    if last_seen:
        entity.last_seen_at = last_seen


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--country", default="mk")
    parser.add_argument("--apply", action="store_true", help="Write changes to the database")
    parser.add_argument(
        "--transition-auto",
        action="store_true",
        help="Queue legacy AUTO entities for review and hide exact known noise",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=5000,
        help="Maximum legacy AUTO rows to transition per run",
    )
    args = parser.parse_args()

    filename = "north_macedonia.yaml" if args.country == "mk" else f"{args.country}.yaml"
    path = ROOT / "config" / "entities" / filename
    if not path.exists():
        print(f"Entity lexicon not found: {path}")
        return 1
    with path.open(encoding="utf-8") as handle:
        items = (yaml.safe_load(handle) or {}).get("entities", [])

    owner_by_alias = {}
    collisions = []
    for item in items:
        owner = EntityExtractor._canonicalize(str(item.get("name", "")))
        for raw_value in [item.get("name", ""), *(item.get("aliases", []) or [])]:
            value = alias_value(raw_value)
            alias = EntityExtractor._canonicalize(value)
            if alias in owner_by_alias and owner_by_alias[alias] != owner:
                collisions.append((alias, owner_by_alias[alias], owner))
            owner_by_alias[alias] = owner
    if collisions:
        for alias, left, right in collisions:
            print(f"Alias collision: {alias} -> {left} / {right}")
        return 1

    engine = get_engine(settings.database_url)
    create_all_tables(engine)
    Session = get_session_factory(engine)
    session = Session()
    stats = {
        "curated": 0,
        "created": 0,
        "approved": 0,
        "merged": 0,
        "auto_curated": 0,
        "auto_needs_review": 0,
        "auto_hidden_noise": 0,
    }
    actions = []
    try:
        for item in items:
            name = str(item.get("name", "")).strip()
            entity_type = EntityType(str(item.get("type", "")))
            aliases = [
                alias_value(value)
                for value in item.get("aliases", []) or []
                if alias_value(value)
            ]
            canonical = EntityExtractor._canonicalize(name)
            candidates = {canonical, *(EntityExtractor._canonicalize(value) for value in aliases)}
            matches = (
                session.query(Entity)
                .filter(Entity.canonical_name.in_(candidates))
                .order_by(Entity.total_mentions.desc(), Entity.id.asc())
                .all()
            )
            target = next(
                (
                    entity for entity in matches
                    if entity.canonical_name == canonical and entity.entity_type == entity_type
                ),
                None,
            )
            if target is None:
                target = next(
                    (
                        entity for entity in matches
                        if entity.entity_type == entity_type
                        and entity.status != EntityStatus.HIDDEN
                    ),
                    matches[0] if matches else None,
                )
            merge_sources = [
                entity for entity in matches
                if (target is None or entity.id != target.id)
                and entity.status != EntityStatus.HIDDEN
            ]

            stats["curated"] += 1
            if not args.apply:
                actions.append({
                    "name": name,
                    "target": target.name if target else "CREATE",
                    "merge_count": len(merge_sources),
                })
                stats["created"] += int(target is None)
                stats["approved"] += int(target is None or target.status != EntityStatus.APPROVED)
                stats["merged"] += len(merge_sources)
                continue

            now = datetime.datetime.utcnow()
            if target is None:
                target = Entity(
                    name=name,
                    canonical_name=canonical,
                    search_text=search_blob(name, canonical, *aliases),
                    entity_type=entity_type,
                    status=EntityStatus.APPROVED,
                    metadata_json={
                        "aliases": aliases,
                        "matched_aliases": aliases,
                        "curated_country": args.country,
                        "provenance": ["curated_lexicon"],
                        "confidence": 1.0,
                        "publishable": True,
                        "trust_tier": "curated",
                        "decision_reasons": ["validated_registry_alias"],
                    },
                    review_notes="Created from curated country entity lexicon.",
                    reviewed_at=now,
                    total_mentions=0,
                )
                session.add(target)
                session.flush()
                stats["created"] += 1
            else:
                was_approved = target.status == EntityStatus.APPROVED
                target.name = name
                target.canonical_name = canonical
                target.entity_type = entity_type
                target.search_text = search_blob(name, canonical, *aliases)
                metadata = dict(target.metadata_json or {})
                provenance = metadata.get("provenance", [])
                if isinstance(provenance, str):
                    provenance = [provenance]
                metadata.update({
                    "aliases": aliases,
                    "matched_aliases": aliases,
                    "curated_country": args.country,
                    "provenance": sorted({*provenance, "curated_lexicon"}),
                    "confidence": 1.0,
                    "publishable": True,
                    "trust_tier": "curated",
                    "decision_reasons": ["validated_registry_alias"],
                })
                target.metadata_json = metadata
                target.status = EntityStatus.APPROVED
                target.review_notes = "Approved from curated country entity lexicon."
                target.reviewed_at = now
                stats["approved"] += int(not was_approved)

            for source in merge_sources:
                _merge(session, source, target)
                stats["merged"] += 1
            _refresh_totals(session, target)

        if args.transition_auto:
            legacy_auto = (
                session.query(Entity)
                .filter(Entity.status == EntityStatus.AUTO)
                .order_by(Entity.id.asc())
                .limit(max(args.batch_size, 1))
                .all()
            )
            for entity in legacy_auto:
                canonical = EntityExtractor._canonicalize(entity.name)
                if canonical in owner_by_alias:
                    # The curated sync above owns this record. In dry-run mode,
                    # report it separately instead of misclassifying it.
                    stats["auto_curated"] += 1
                    continue
                if EntityExtractor.is_explicit_noise(entity.name):
                    stats["auto_hidden_noise"] += 1
                    if args.apply:
                        entity.status = EntityStatus.HIDDEN
                        entity.review_notes = "Hidden by exact legacy-noise migration rule."
                        entity.reviewed_at = datetime.datetime.utcnow()
                    continue
                stats["auto_needs_review"] += 1
                if args.apply:
                    entity.status = EntityStatus.NEEDS_REVIEW
                    entity.review_notes = "Queued by precision-first legacy AUTO migration."

        session.commit()
        mode = "Applied" if args.apply else "Dry run"
        print(
            f"{mode}: curated={stats['curated']} created={stats['created']} "
            f"approved={stats['approved']} merged={stats['merged']} "
            f"auto_curated={stats['auto_curated']} "
            f"auto_needs_review={stats['auto_needs_review']} "
            f"auto_hidden_noise={stats['auto_hidden_noise']}"
        )
        if not args.apply:
            for action in actions[:30]:
                if action["target"] == "CREATE" or action["merge_count"]:
                    print(
                        f"  {action['name']}: target={action['target']} "
                        f"merge={action['merge_count']}"
                    )
            print("Add --apply to approve/merge curated records and apply requested transitions.")
        return 0
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
