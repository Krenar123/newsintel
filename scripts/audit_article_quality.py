#!/usr/bin/env python3
"""Report likely non-article pages already stored in the database."""

import argparse
import datetime
import sys
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import func

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import settings
from src.ingestion.scraper import ArticleScraper
from src.models.database import (
    Article, ArticleCategory, Entity, EntityMention, Source, StoryCluster,
    StoryClusterArticle, Summary, get_engine, get_session_factory,
)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Audit stored article quality")
    parser.add_argument("--country", default=settings.default_country)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--source", default="", help="Only include sources containing this text")
    parser.add_argument("--method", default="scrape", help="Filter by ingestion method, or 'all'")
    parser.add_argument("--include-excluded", action="store_true", help="Also audit rows already excluded from active intelligence")
    parser.add_argument("--apply", action="store_true", help="Actually modify the database")
    parser.add_argument("--exclude", action="store_true", help="Mark suspect articles excluded from intelligence without deleting them")
    parser.add_argument("--delete", action="store_true", help="Delete suspect article rows and related processing rows")
    args = parser.parse_args()

    session_factory = get_session_factory(get_engine(settings.database_url))
    db = session_factory()
    try:
        query = (
            db.query(Article)
            .join(Source, Source.id == Article.source_id)
            .filter(Source.country_code == args.country)
        )
        if args.source:
            query = query.filter(Source.name.ilike(f"%{args.source}%"))
        if args.method != "all":
            query = query.filter(Article.ingestion_method == args.method)
        if not args.include_excluded:
            query = query.filter(Article.quality_status != "excluded")
        query = query.order_by(Article.ingested_at.desc()).limit(max(args.limit * 5, args.limit))

        rows = []
        for article in query.all():
            reasons = quality_reasons(article)
            if reasons:
                rows.append((article, reasons))
            if len(rows) >= args.limit:
                break

        print("ID | Source | Reasons | Title | URL")
        print("-" * 140)
        for article, reasons in rows:
            print(
                " | ".join([
                    str(article.id),
                    (article.source.name if article.source else "Unknown")[:22],
                    ",".join(reasons)[:36],
                    (article.title or "")[:52],
                    (article.url or "")[:90],
                ])
            )
        print(f"\nSuspect articles shown: {len(rows)}")
        if rows and args.exclude:
            if not args.apply:
                print("\nDry run only. Re-run with --apply --exclude to mark these rows excluded.")
            else:
                excluded = exclude_suspect_articles(db, rows)
                print(f"\nExcluded {excluded} articles from intelligence outputs. Rows remain stored for audit.")
        if rows and args.delete:
            if not args.apply:
                print("\nDry run only. Re-run with --apply --delete to remove these rows.")
            else:
                deleted = delete_suspect_articles(db, [article for article, _ in rows])
                print(
                    "\nDeleted "
                    f"{deleted['articles']} articles, "
                    f"{deleted['mentions']} mentions, "
                    f"{deleted['summaries']} summaries, "
                    f"{deleted['categories']} categories, "
                    f"{deleted['cluster_links']} cluster links. "
                    "Rebuild story clusters after cleanup."
                )
    finally:
        db.close()


def quality_reasons(article: Article) -> list[str]:
    reasons = []
    url = article.url or ""
    title = article.title or ""
    content = article.content or ""
    parsed = urlparse(url)
    path_parts = [part for part in parsed.path.strip("/").split("/") if part]
    source_domain = ""
    if article.source and article.source.url:
        source_domain = urlparse(article.source.url).netloc.replace("www.", "")

    reject_reason = ArticleScraper._url_reject_reason(url, source_domain=source_domain)
    if reject_reason not in {None, "external_domain", "not_in_include_patterns"}:
        reasons.append(reject_reason)
    is_rss = (article.ingestion_method or "").lower() == "rss"
    min_word_count = 15 if is_rss else 40
    min_unique_words = 8 if is_rss else 25
    if len(content.split()) < min_word_count:
        reasons.append("short_content")
    if ArticleScraper._content_quality_error(
        title=title,
        content=content,
        canonical_url=url,
        published_at=article.published_at,
        min_word_count=min_word_count,
        min_unique_words=min_unique_words,
    ):
        reasons.append("content_quality")
    return sorted(set(reasons))


def exclude_suspect_articles(db, rows: list[tuple[Article, list[str]]]) -> int:
    now = datetime.datetime.utcnow()
    count = 0
    for article, reasons in rows:
        article.quality_status = "excluded"
        article.quality_notes = f"Excluded by article quality audit: {', '.join(reasons)}"
        article.quality_reviewed_at = now
        article.is_processed = True
        article.processing_error = "Excluded from intelligence by article quality audit"
        count += 1
    db.commit()
    return count


def delete_suspect_articles(db, articles: list[Article]) -> dict[str, int]:
    article_ids = [article.id for article in articles]
    if not article_ids:
        return {
            "articles": 0,
            "mentions": 0,
            "summaries": 0,
            "categories": 0,
            "cluster_links": 0,
        }

    entity_ids = [
        row[0]
        for row in db.query(EntityMention.entity_id)
        .filter(EntityMention.article_id.in_(article_ids))
        .distinct()
        .all()
    ]
    cluster_ids = [
        row[0]
        for row in db.query(StoryClusterArticle.cluster_id)
        .filter(StoryClusterArticle.article_id.in_(article_ids))
        .distinct()
        .all()
    ]

    counts = {
        "mentions": db.query(EntityMention).filter(EntityMention.article_id.in_(article_ids)).delete(synchronize_session=False),
        "summaries": db.query(Summary).filter(Summary.article_id.in_(article_ids)).delete(synchronize_session=False),
        "categories": db.query(ArticleCategory).filter(ArticleCategory.article_id.in_(article_ids)).delete(synchronize_session=False),
        "cluster_links": db.query(StoryClusterArticle).filter(StoryClusterArticle.article_id.in_(article_ids)).delete(synchronize_session=False),
        "articles": db.query(Article).filter(Article.id.in_(article_ids)).delete(synchronize_session=False),
    }

    for entity_id in entity_ids:
        mention_count = (
            db.query(func.coalesce(func.sum(EntityMention.mention_count), 0))
            .filter(EntityMention.entity_id == entity_id)
            .scalar()
        )
        entity = db.query(Entity).get(entity_id)
        if entity:
            entity.total_mentions = mention_count

    for cluster_id in cluster_ids:
        cluster = db.query(StoryCluster).get(cluster_id)
        if not cluster:
            continue
        links = (
            db.query(StoryClusterArticle)
            .filter(StoryClusterArticle.cluster_id == cluster_id)
            .all()
        )
        if not links:
            db.delete(cluster)
            continue
        cluster.article_count = len(links)
        cluster.source_count = len({link.source_id for link in links})
        if cluster.source_count <= 1:
            cluster.status = "single_source"

    db.commit()
    return counts


if __name__ == "__main__":
    main()
