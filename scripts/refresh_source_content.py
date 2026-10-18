#!/usr/bin/env python3
"""Re-extract stored source articles after scraper selector improvements.

Dry run:
    python scripts/refresh_source_content.py --source Makfax --limit 20

Apply and rebuild derived NLP rows:
    python scripts/refresh_source_content.py --source Makfax --limit 50 --apply
"""

import argparse
import datetime
import sys
from pathlib import Path

import yaml
from sqlalchemy import func

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import settings
from src.ingestion.rss_fetcher import RawArticle
from src.ingestion.scraper import ArticleScraper
from src.models.database import (
    Article,
    ArticleCategory,
    Entity,
    EntityMention,
    Source,
    StoryClusterArticle,
    Summary,
    create_all_tables,
    get_engine,
    get_session_factory,
)
from src.processing.pipeline import ProcessingPipeline
from src.search.normalization import search_blob


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(
        description="Refresh stored articles using the current per-source scraper selectors"
    )
    parser.add_argument("--source", required=True, help="Exact configured source name")
    parser.add_argument("--country", default="mk")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--delay", type=float, default=0.25)
    parser.add_argument("--include-rss", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    country_config = _load_country_config(args.country)
    source_config = next(
        (item for item in country_config.get("sources", []) if item.get("name") == args.source),
        None,
    )
    if not source_config:
        raise SystemExit(f"Configured source not found: {args.source}")
    scraper_config = source_config.get("scraper") or {}
    if not scraper_config.get("enabled"):
        raise SystemExit(f"Scraper is disabled for source: {args.source}")

    engine = get_engine(settings.database_url)
    create_all_tables(engine)
    session = get_session_factory(engine)()
    scraper = ArticleScraper(delay_seconds=args.delay, max_articles_per_source=args.limit)

    stats = {
        "checked": 0,
        "changed": 0,
        "unchanged": 0,
        "failed": 0,
        "hash_conflicts": 0,
        "reprocessed": 0,
    }
    changed_articles: list[Article] = []
    touched_entity_ids: set[int] = set()

    try:
        source = session.query(Source).filter(Source.name == args.source).first()
        if not source:
            raise SystemExit(f"Database source not found: {args.source}")

        query = session.query(Article).filter(Article.source_id == source.id)
        if not args.include_rss:
            query = query.filter(Article.ingestion_method == "scrape")
        articles = (
            query.order_by(
                func.coalesce(Article.published_at, Article.fetched_at).desc(),
                Article.id.desc(),
            )
            .offset(args.offset)
            .limit(args.limit)
            .all()
        )

        for article in articles:
            stats["checked"] += 1
            result = scraper.scrape_article(article.url, scraper_config)
            if not result.success:
                stats["failed"] += 1
                print(f"FAIL {article.id}: {result.error} {article.url}")
                continue
            if _same_content(article, result.title, result.content):
                stats["unchanged"] += 1
                continue

            replacement = RawArticle(
                url=result.url,
                title=result.title,
                content=result.content,
            )
            replacement.compute_hash()
            conflicting_id = (
                session.query(Article.id)
                .filter(
                    Article.content_hash == replacement.content_hash,
                    Article.id != article.id,
                )
                .scalar()
            )
            if conflicting_id:
                stats["hash_conflicts"] += 1
                print(f"HASH CONFLICT {article.id} -> existing article {conflicting_id}")
                continue

            stats["changed"] += 1
            print(
                f"CHANGE {article.id}: {article.word_count or 0} -> {result.word_count} words | "
                f"{article.title[:90]}"
            )
            if not args.apply:
                continue

            old_mentions = (
                session.query(EntityMention)
                .filter(EntityMention.article_id == article.id)
                .all()
            )
            touched_entity_ids.update(mention.entity_id for mention in old_mentions)
            session.query(EntityMention).filter(EntityMention.article_id == article.id).delete(
                synchronize_session=False
            )
            session.query(Summary).filter(Summary.article_id == article.id).delete(
                synchronize_session=False
            )
            session.query(ArticleCategory).filter(ArticleCategory.article_id == article.id).delete(
                synchronize_session=False
            )
            session.query(StoryClusterArticle).filter(
                StoryClusterArticle.article_id == article.id
            ).delete(synchronize_session=False)

            article.url = result.url
            article.title = result.title
            article.content = result.content
            article.search_text = search_blob(result.title, result.content, result.author)
            article.author = result.author or article.author
            article.published_at = result.published_at or article.published_at
            article.image_url = result.image_url or article.image_url
            article.raw_html = result.html
            article.word_count = result.word_count
            article.content_hash = replacement.content_hash
            article.is_processed = False
            article.processing_error = None
            article.quality_status = "active"
            article.quality_notes = (
                f"Content refreshed from source selectors at "
                f"{datetime.datetime.utcnow().isoformat()}Z"
            )
            changed_articles.append(article)

        if not args.apply:
            print(_summary(stats, applied=False))
            return 0

        session.commit()
        pipeline = ProcessingPipeline(session, languages=["mk", "en", "sq"])
        for article in changed_articles:
            try:
                pipeline._process_single(article)
                article.is_processed = True
                article.processing_error = None
                session.flush()
                touched_entity_ids.update(
                    entity_id
                    for (entity_id,) in session.query(EntityMention.entity_id)
                    .filter(EntityMention.article_id == article.id)
                    .all()
                )
                session.commit()
                stats["reprocessed"] += 1
            except Exception as exc:
                session.rollback()
                article = session.get(Article, article.id)
                if article:
                    article.processing_error = f"Content refresh reprocessing failed: {exc}"
                    article.is_processed = False
                    session.commit()
                print(f"REPROCESS FAIL {article.id if article else '?'}: {exc}")

        _recompute_entities(session, touched_entity_ids)
        session.commit()
        print(_summary(stats, applied=True))
        print("Story-cluster links for changed articles were cleared; run a recent cluster rebuild.")
        return 0 if stats["failed"] == 0 else 1
    finally:
        scraper.close()
        session.close()
        engine.dispose()


def _same_content(article: Article, title: str, content: str) -> bool:
    return article.title.strip() == title.strip() and (article.content or "").strip() == content.strip()


def _recompute_entities(session, entity_ids: set[int]) -> None:
    for entity_id in entity_ids:
        entity = session.get(Entity, entity_id)
        if not entity:
            continue
        total_mentions = (
            session.query(func.coalesce(func.sum(EntityMention.mention_count), 0))
            .filter(EntityMention.entity_id == entity_id)
            .scalar()
        )
        last_seen = (
            session.query(func.max(func.coalesce(Article.published_at, Article.fetched_at)))
            .join(EntityMention, EntityMention.article_id == Article.id)
            .filter(EntityMention.entity_id == entity_id)
            .scalar()
        )
        entity.total_mentions = int(total_mentions or 0)
        if last_seen is not None:
            entity.last_seen_at = last_seen


def _load_country_config(country_code: str) -> dict:
    config_name = {"mk": "north_macedonia"}.get(country_code, country_code)
    path = settings.countries_dir / f"{config_name}.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _summary(stats: dict, applied: bool) -> str:
    mode = "APPLIED" if applied else "DRY RUN"
    return (
        f"{mode}: checked={stats['checked']} changed={stats['changed']} "
        f"unchanged={stats['unchanged']} failed={stats['failed']} "
        f"hash_conflicts={stats['hash_conflicts']} reprocessed={stats['reprocessed']}"
    )


if __name__ == "__main__":
    raise SystemExit(main())
