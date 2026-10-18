#!/usr/bin/env python3
"""
Ingest articles from configured country sources.

Usage:
    python scripts/ingest.py                    # Default country
    python scripts/ingest.py --country mk       # Specific country
    python scripts/ingest.py --country mk --process  # Ingest + process
    python scripts/ingest.py --process-only     # Only process unprocessed
    python scripts/ingest.py --train            # Train ML categorizer

Can also be run on a cron schedule:
    */60 * * * * cd /path/to/newsintel && python scripts/ingest.py --country mk --process
"""

import sys
import argparse
import atexit
import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import yaml
from config import settings
from src.models.database import (
    get_engine, get_session_factory, create_all_tables,
    FacebookPageMonitor, IngestionRun, IngestionSourceStat,
)
from src.ingestion.rss_fetcher import RSSFetcher
from src.ingestion.scraper import ArticleScraper
from src.ingestion.facebook_fetcher import FacebookPageFetcher
from src.ingestion.url_filter import unknown_article_urls
from src.processing.pipeline import ProcessingPipeline
from src.processing.story_clustering import StoryClusterer
from src.logging_config import configure_logging
from src.operations.process_lock import ProcessFileLock


def main():
    configure_logging(settings.log_level, json_logs=settings.app_env.lower() in {"production", "prod"})
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="NewsIntel article ingestion")
    parser.add_argument(
        "--country", default=settings.default_country,
        help="Country code (e.g., mk, rs, al)",
    )
    parser.add_argument(
        "--process", action="store_true",
        help="Also process articles after ingestion",
    )
    parser.add_argument(
        "--process-only", action="store_true",
        help="Only process unprocessed articles (skip ingestion)",
    )
    parser.add_argument(
        "--train", action="store_true",
        help="Train ML categorizer on accumulated data",
    )
    parser.add_argument(
        "--batch-size", type=int, default=100,
        help="Number of articles to process per batch",
    )
    parser.add_argument(
        "--translate-to", default=None,
        help="Translate summaries to this language (e.g., en)",
    )
    parser.add_argument(
        "--stop-after-duplicates",
        type=int,
        default=settings.stop_after_consecutive_duplicates,
        help="Stop a source after this many consecutive duplicates (0 disables)",
    )
    parser.add_argument(
        "--skip-clustering",
        action="store_true",
        help="Skip rebuilding cross-source story clusters after ingestion/processing",
    )
    args = parser.parse_args()
    duplicate_stop_threshold = args.stop_after_duplicates or None

    operation_lock = ProcessFileLock(settings.base_dir / "data" / "ingestion_job.lock")
    if not operation_lock.acquire():
        print("Another ingestion or processing job is already running.", file=sys.stderr)
        return 2
    atexit.register(operation_lock.release)

    # Database
    engine = get_engine(settings.database_url)
    create_all_tables(engine)
    Session = get_session_factory(engine)
    session = Session()

    # Filename mapping
    code_to_file = {
        "mk": "north_macedonia",
    }
    config_filename = code_to_file.get(args.country, args.country)
    config_path = settings.countries_dir / f"{config_filename}.yaml"

    if not config_path.exists():
        print(f"Error: Country config not found: {config_path}")
        sys.exit(1)

    with open(config_path, encoding="utf-8") as f:
        country_config = yaml.safe_load(f)

    # Initialize pipeline
    pipeline = ProcessingPipeline(
        session=session,
        enable_ai=settings.enable_ai_summaries,
        api_key=settings.anthropic_api_key,
        model_path=settings.models_dir,
        languages=country_config.get("languages", ["en"]),
    )

    # ── Step 1: Ingest ────────────────────────────────────────────
    if not args.process_only:
        print(f"\n{'='*60}")
        print(f"INGESTING: {country_config.get('name', args.country)}")
        print(f"{'='*60}")

        fetcher = RSSFetcher(
            delay_seconds=settings.scrape_delay_seconds,
            max_articles=settings.max_articles_per_feed,
        )
        scraper = ArticleScraper(
            delay_seconds=settings.scrape_delay_seconds,
            max_articles_per_source=settings.max_articles_per_feed,
        )
        facebook = FacebookPageFetcher(
            access_token=settings.facebook_access_token,
            api_version=settings.facebook_api_version,
            delay_seconds=settings.scrape_delay_seconds,
            max_posts_per_page=settings.max_facebook_posts_per_page,
        )

        sources = country_config.get("sources", [])
        run = IngestionRun(
            country_code=args.country,
            run_type="ingest",
            status="running",
            total_sources=len(sources),
        )
        session.add(run)
        session.commit()
        total_stats = {
            "total": 0,
            "new": 0,
            "duplicate": 0,
            "duplicate_fuzzy": 0,
            "error": 0,
        }
        for i, source in enumerate(sources, 1):
            source = {**source, "country_code": country_config.get("code", args.country)}
            print(f"\n[{i}/{len(sources)}] {source['name']}")
            if source.get("is_active", True) is False:
                _record_source_stat(
                    session=session,
                    run=run,
                    source=source,
                    discovered_urls=0,
                    scraped_count=0,
                    rss_count=0,
                    stats={"total": 0, "checked": 0, "new": 0, "duplicate": 0, "duplicate_fuzzy": 0, "error": 0},
                    status="disabled",
                    raw_articles=[],
                )
                print("    -> Source disabled in YAML; skipped")
                continue
            scraper_enabled = bool((source.get("scraper") or {}).get("enabled"))
            discovered_urls = scraper.discover_article_urls(source) if scraper_enabled else []
            discovered = len(discovered_urls)
            scrape_urls = unknown_article_urls(session, discovered_urls)
            known_urls = discovered - len(scrape_urls)
            if known_urls:
                print(f"    -> Skipped {known_urls} already stored scraper URLs")
            scraped = scraper.scrape_source(source, article_urls=scrape_urls)
            print(f"    -> Scraped {len(scraped)} articles")
            articles = fetcher.fetch_all_feeds(source) if source.get("rss_enabled", True) else []
            print(f"    → Fetched {len(articles)} articles")
            source_articles = scraped + articles
            stats = pipeline.ingest_articles(
                source_articles,
                stop_after_consecutive_duplicates=duplicate_stop_threshold,
            )
            _add_stats(total_stats, stats)
            _record_source_stat(
                session=session,
                run=run,
                source=source,
                discovered_urls=discovered,
                scraped_count=len(scraped),
                rss_count=len(articles),
                stats=stats,
                status=_source_status(
                    discovered,
                    len(scraped),
                    stats,
                    known_urls=known_urls,
                ),
                raw_articles=source_articles,
            )
            print(
                f"    -> New {stats['new']} | Dup {stats['duplicate']} | "
                f"Fuzzy {stats.get('duplicate_fuzzy', 0)} | Errors {stats['error']}"
                f"{' | stopped early' if stats.get('stopped_early') else ''}"
            )

        _merge_facebook_monitors(country_config, session, args.country)
        facebook_articles = facebook.fetch_all_pages(country_config)
        if country_config.get("facebook_pages"):
            print(f"\nFacebook pages: {len(facebook_articles)} posts")
        if facebook_articles:
            stats = pipeline.ingest_articles(
                facebook_articles,
                stop_after_consecutive_duplicates=duplicate_stop_threshold,
            )
            _add_stats(total_stats, stats)
            _record_source_stat(
                session=session,
                run=run,
                source={
                    "name": "Facebook Pages",
                    "url": "https://facebook.com",
                    "source_type": "social_media",
                    "scraper": {"enabled": False},
                    "rss_feeds": [],
                },
                discovered_urls=0,
                scraped_count=0,
                rss_count=0,
                stats=stats,
                status="healthy" if stats["new"] or stats["duplicate"] else "no_posts",
                raw_articles=facebook_articles,
            )

        facebook.close()
        scraper.close()
        fetcher.close()

        run.status = "completed"
        run.finished_at = datetime.datetime.utcnow()
        run.total_raw = total_stats["total"]
        run.total_new = total_stats["new"]
        run.total_duplicate = total_stats["duplicate"]
        run.total_duplicate_fuzzy = total_stats["duplicate_fuzzy"]
        run.total_error = total_stats["error"]
        session.commit()

        stats = total_stats
        print(f"\nTotal raw articles: {stats['total']}")
        print(f"\nIngestion results:")
        print(f"  New:       {stats['new']}")
        print(f"  Duplicate: {stats['duplicate']}")
        print(f"  Fuzzy dup: {stats.get('duplicate_fuzzy', 0)}")
        print(f"  Errors:    {stats['error']}")

    # ── Step 2: Process ───────────────────────────────────────────
    if args.process or args.process_only:
        print(f"\n{'='*60}")
        print(f"PROCESSING ARTICLES")
        print(f"{'='*60}")

        stats = pipeline.process_unprocessed(
            batch_size=args.batch_size,
            translate_to=args.translate_to,
        )
        print(f"\nProcessing results:")
        print(f"  Processed: {stats['processed']}")
        print(f"  Errors:    {stats['errors']}")

    # ── Step 3: Train (optional) ──────────────────────────────────
    if args.train:
        print(f"\n{'='*60}")
        print(f"TRAINING ML CATEGORIZER")
        print(f"{'='*60}")

        metrics = pipeline.train_categorizer(min_samples=50)
        if metrics:
            print(f"\nTraining results:")
            print(f"  Accuracy:   {metrics['accuracy_mean']:.1%} "
                  f"(±{metrics['accuracy_std']:.1%})")
            print(f"  Samples:    {metrics['num_samples']}")
            print(f"  Categories: {metrics['num_categories']}")
        else:
            print("Not enough data for training yet.")

    if not args.skip_clustering:
        print(f"\n{'='*60}")
        print("CLUSTERING STORIES")
        print(f"{'='*60}")
        cluster_stats = StoryClusterer(session).rebuild(
            country_code=args.country,
            days=settings.story_cluster_days,
            limit=settings.story_cluster_limit,
        )
        print(f"  Articles considered: {cluster_stats['articles_considered']}")
        print(f"  Clusters created:    {cluster_stats['clusters_created']}")
        print(f"  Article links:       {cluster_stats['cluster_links']}")

    session.close()
    engine.dispose()
    print("\nDone.")


def _add_stats(total: dict, stats: dict):
    total["total"] += stats.get("total", 0)
    total["new"] += stats.get("new", 0)
    total["duplicate"] += stats.get("duplicate", 0)
    total["duplicate_fuzzy"] += stats.get("duplicate_fuzzy", 0)
    total["error"] += stats.get("error", 0)


def _source_status(
    discovered_urls: int,
    scraped_count: int,
    stats: dict,
    known_urls: int = 0,
) -> str:
    if stats.get("stopped_early"):
        return "caught_up"
    if stats.get("error", 0) and not stats.get("new", 0) and not stats.get("duplicate", 0):
        return "error"
    if discovered_urls == 0 and scraped_count == 0:
        return "rss_only" if stats.get("total", 0) else "failing"
    if discovered_urls and known_urls == discovered_urls and scraped_count == 0:
        return "caught_up"
    if scraped_count == 0:
        return "rss_only" if stats.get("total", 0) else "no_links"
    if stats.get("new", 0) or stats.get("duplicate", 0) or stats.get("duplicate_fuzzy", 0):
        return "healthy"
    return "degraded"


def _record_source_stat(
    session,
    run: IngestionRun,
    source: dict,
    discovered_urls: int,
    scraped_count: int,
    rss_count: int,
    stats: dict,
    status: str,
    raw_articles: list,
):
    word_counts = [
        len(article.content.split())
        for article in raw_articles
        if getattr(article, "content", None)
    ]
    average_word_count = (
        round(sum(word_counts) / len(word_counts), 1)
        if word_counts else 0.0
    )
    session.add(IngestionSourceStat(
        run_id=run.id,
        source_name=source.get("name", ""),
        source_url=source.get("url"),
        source_type=source.get("source_type", "news"),
        scraper_enabled=bool((source.get("scraper") or {}).get("enabled")),
        rss_enabled=bool(source.get("rss_feeds")),
        discovered_urls=discovered_urls,
        scraped_count=scraped_count,
        rss_count=rss_count,
        raw_count=stats.get("total", 0),
        checked_count=stats.get("checked", stats.get("total", 0)),
        new_count=stats.get("new", 0),
        duplicate_count=stats.get("duplicate", 0),
        duplicate_fuzzy_count=stats.get("duplicate_fuzzy", 0),
        duplicate_streak=stats.get("duplicate_streak", 0),
        stopped_early=bool(stats.get("stopped_early")),
        error_count=stats.get("error", 0),
        success_count=(
            stats.get("new", 0)
            + stats.get("duplicate", 0)
            + stats.get("duplicate_fuzzy", 0)
        ),
        failed_count=stats.get("error", 0),
        average_word_count=average_word_count,
        status=status,
    ))
    session.commit()


def _merge_facebook_monitors(country_config: dict, session, country_code: str):
    pages = list(country_config.get("facebook_pages", []))
    existing = {
        page.get("url") or page.get("page_handle") or page.get("page_id")
        for page in pages
    }
    monitors = (
        session.query(FacebookPageMonitor)
        .filter(
            FacebookPageMonitor.country_code == country_code,
            FacebookPageMonitor.is_active == True,
        )
        .all()
    )
    for monitor in monitors:
        key = monitor.url or monitor.page_handle or monitor.page_id
        if key in existing:
            continue
        pages.append({
            "name": monitor.name,
            "url": monitor.url,
            "page_handle": monitor.page_handle,
            "page_id": monitor.page_id,
            "enabled": monitor.is_active,
            "language": monitor.language,
            "source_type": monitor.source_type,
            "political_leaning": monitor.political_leaning,
            "ownership": monitor.ownership,
            "reliability_score": monitor.reliability_score,
            "monitor_type": monitor.monitor_type,
        })
    country_config["facebook_pages"] = pages


if __name__ == "__main__":
    raise SystemExit(main() or 0)
