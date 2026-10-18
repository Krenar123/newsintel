#!/usr/bin/env python3
"""
Scheduler — Runs ingestion, processing, and report delivery on a schedule.

This is the main long-running process for production. It handles:
  - Frequent article ingestion from all configured countries
  - Immediate processing of new articles
  - Daily/weekly report generation and email delivery to subscribers
  - Periodic ML model retraining

Usage:
    python scripts/scheduler.py                 # Run all jobs
    python scripts/scheduler.py --no-email      # Skip email delivery
    python scripts/scheduler.py --country mk    # Single country only

For production, run this as a systemd service or in Docker (see docker-compose.yml).
"""

import sys
import argparse
import atexit
import datetime
import json
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import yaml
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from config import settings
from src.models.database import (
    get_engine, get_session_factory, Subscription, SubscriptionFrequency,
    FacebookPageMonitor, IngestionRun, IngestionSourceStat, create_all_tables,
)
from src.ingestion.rss_fetcher import RSSFetcher
from src.ingestion.scraper import ArticleScraper
from src.ingestion.facebook_fetcher import FacebookPageFetcher
from src.ingestion.url_filter import unknown_article_urls
from src.processing.pipeline import ProcessingPipeline
from src.processing.story_clustering import StoryClusterer
from src.delivery.pdf_report import PDFReportGenerator, ReportConfig
from src.delivery.email_sender import EmailSender
from src.logging_config import configure_logging
from src.operations.process_lock import ProcessFileLock

import structlog

configure_logging(settings.log_level, json_logs=settings.app_env.lower() in {"production", "prod"})
logger = structlog.get_logger()

# ── Globals ───────────────────────────────────────────────────────────
engine = None
SessionFactory = None
COUNTRIES = {}
SEND_EMAIL = True
INSTANCE_LOCK = None


def write_heartbeat(status: str, country_code: str = None, run_id: int = None, error: str = None):
    payload = {
        "status": status,
        "country_code": country_code,
        "run_id": run_id,
        "updated_at": datetime.datetime.utcnow().isoformat(),
        "email_enabled": SEND_EMAIL,
    }
    if error:
        payload["error"] = error
    path = settings.base_dir / "data" / "scheduler_heartbeat.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def init():
    """Initialize database and load country configs."""
    global engine, SessionFactory, COUNTRIES

    engine = get_engine(settings.database_url)
    create_all_tables(engine)
    SessionFactory = get_session_factory(engine)
    _recover_interrupted_runs()

    # Load all country configs
    for config_file in settings.countries_dir.glob("*.yaml"):
        with open(config_file, encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        COUNTRIES[cfg["code"]] = cfg

    logger.info(
        "scheduler_initialized",
        countries=list(COUNTRIES.keys()),
        ai_enabled=settings.enable_ai_summaries,
    )


def _recover_interrupted_runs():
    """Close scheduled runs left open by a stopped or crashed scheduler."""
    session = SessionFactory()
    try:
        runs = (
            session.query(IngestionRun)
            .filter(
                IngestionRun.run_type == "scheduled_ingest",
                IngestionRun.status == "running",
            )
            .all()
        )
        if not runs:
            return
        now = datetime.datetime.utcnow()
        for run in runs:
            run.status = "interrupted"
            run.finished_at = now
            run.notes = "Recovered when a new scheduler process started; previous run did not finish."
        session.commit()
        logger.warning("recovered_interrupted_runs", count=len(runs))
    finally:
        session.close()


def _exclusive_ingestion_job(function):
    """Skip a cycle cleanly when another ingestion or processing job is active."""
    def wrapped(*args, **kwargs):
        lock = ProcessFileLock(settings.base_dir / "data" / "ingestion_job.lock")
        if not lock.acquire():
            country_code = kwargs.get("country_code")
            logger.warning("ingestion_job_skipped_busy", country=country_code)
            write_heartbeat("job_skipped_busy", country_code=country_code)
            return {"status": "busy"}
        try:
            return function(*args, **kwargs)
        finally:
            lock.release()
    return wrapped


# ── Job: Ingest + Process ────────────────────────────────────────────

@_exclusive_ingestion_job
def job_ingest_and_process(country_code: str = None):
    """Fetch new articles and process them."""
    session = SessionFactory()
    codes = [country_code] if country_code else list(COUNTRIES.keys())
    write_heartbeat("job_started", country_code=country_code)

    for code in codes:
        cfg = COUNTRIES.get(code)
        if not cfg:
            logger.warning("country_not_found", code=code)
            continue

        logger.info("ingestion_start", country=cfg["name"])

        run = IngestionRun(
            country_code=code,
            run_type="scheduled_ingest",
            status="running",
            total_sources=len(cfg.get("sources", [])),
        )
        session.add(run)
        session.commit()
        write_heartbeat("run_started", country_code=code, run_id=run.id)

        try:
            # Fetch RSS
            fetcher = RSSFetcher(
                delay_seconds=settings.scrape_delay_seconds,
                max_articles=settings.max_articles_per_feed,
            )
            scheduled_limit = min(
                settings.max_articles_per_feed,
                settings.scheduler_max_articles_per_source,
            )
            scraper = ArticleScraper(
                delay_seconds=settings.scrape_delay_seconds,
                max_articles_per_source=scheduled_limit,
            )
            facebook = FacebookPageFetcher(
                access_token=settings.facebook_access_token,
                api_version=settings.facebook_api_version,
                delay_seconds=settings.scrape_delay_seconds,
                max_posts_per_page=settings.max_facebook_posts_per_page,
            )
            pipeline = ProcessingPipeline(
                session=session,
                enable_ai=settings.enable_ai_summaries,
                api_key=settings.anthropic_api_key,
                model_path=settings.models_dir,
                languages=cfg.get("languages", ["en"]),
            )
            ingest_stats = {
                "total": 0,
                "checked": 0,
                "new": 0,
                "duplicate": 0,
                "duplicate_fuzzy": 0,
                "error": 0,
                "stopped_sources": 0,
            }
            for source in cfg.get("sources", []):
                source = {**source, "country_code": cfg.get("code", code)}
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
                    continue
                scraper_enabled = bool((source.get("scraper") or {}).get("enabled"))
                discovered_urls = (
                    scraper.discover_article_urls(source)
                    if scraper_enabled else []
                )
                discovered = len(discovered_urls)
                scrape_urls = unknown_article_urls(session, discovered_urls)
                known_urls = discovered - len(scrape_urls)
                if known_urls:
                    logger.info(
                        "scrape_known_urls_skipped",
                        source=source.get("name"),
                        known=known_urls,
                        new_candidates=len(scrape_urls),
                    )
                source_articles = scraper.scrape_source(
                    source,
                    article_urls=scrape_urls,
                    max_articles=scheduled_limit,
                )
                articles = fetcher.fetch_all_feeds(source) if source.get("rss_enabled", True) else []
                source_articles.extend(articles)
                source_stats = pipeline.ingest_articles(
                    source_articles,
                    stop_after_consecutive_duplicates=settings.stop_after_consecutive_duplicates,
                )
                _add_ingest_stats(ingest_stats, source_stats)
                _record_source_stat(
                    session=session,
                    run=run,
                    source=source,
                    discovered_urls=discovered,
                    scraped_count=len(source_articles) - len(articles),
                    rss_count=len(articles),
                    stats=source_stats,
                    status=_source_status(
                        discovered,
                        len(source_articles) - len(articles),
                        source_stats,
                        known_urls=known_urls,
                    ),
                    raw_articles=source_articles,
                )
            _merge_facebook_monitors(cfg, session, code)
            facebook_articles = facebook.fetch_all_pages(cfg)
            facebook.close()
            scraper.close()
            fetcher.close()

            facebook_stats = pipeline.ingest_articles(
                facebook_articles,
                stop_after_consecutive_duplicates=settings.stop_after_consecutive_duplicates,
            )
            _add_ingest_stats(ingest_stats, facebook_stats)
            if facebook_articles or cfg.get("facebook_pages"):
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
                    stats=facebook_stats,
                    status="healthy" if facebook_stats["new"] or facebook_stats["duplicate"] else "no_posts",
                    raw_articles=facebook_articles,
                )
            process_stats = _drain_processing_backlog(pipeline)
            cluster_stats = StoryClusterer(session).rebuild(
                country_code=code,
                days=settings.story_cluster_days,
                limit=settings.story_cluster_limit,
            )

            logger.info(
                "ingestion_complete",
                country=cfg["name"],
                new=ingest_stats["new"],
                duplicate=ingest_stats["duplicate"] + ingest_stats["duplicate_fuzzy"],
                stopped_sources=ingest_stats["stopped_sources"],
                processed=process_stats["processed"],
                clusters=cluster_stats["clusters_created"],
            )
            run.status = "completed"
            run.finished_at = datetime.datetime.utcnow()
            run.total_raw = ingest_stats["total"]
            run.total_new = ingest_stats["new"]
            run.total_duplicate = ingest_stats["duplicate"]
            run.total_duplicate_fuzzy = ingest_stats["duplicate_fuzzy"]
            run.total_error = ingest_stats["error"]
            run.notes = (
                f"processed={process_stats['processed']}; "
                f"clusters={cluster_stats['clusters_created']}; "
                f"stopped_sources={ingest_stats['stopped_sources']}"
            )
            session.commit()
            write_heartbeat("run_completed", country_code=code, run_id=run.id)

        except Exception as e:
            session.rollback()
            run.status = "failed"
            run.finished_at = datetime.datetime.utcnow()
            run.notes = str(e)
            session.commit()
            logger.error(
                "ingestion_failed", country=cfg["name"], error=str(e)
            )
            write_heartbeat("run_failed", country_code=code, run_id=run.id, error=str(e))

    session.close()
    write_heartbeat("idle", country_code=country_code)
    return {"status": "completed"}


def _drain_processing_backlog(
    pipeline: ProcessingPipeline,
    batch_size: int = 200,
    max_batches: int = 5,
) -> dict:
    """Process a bounded backlog so one busy ingestion cycle does not leave stale data."""
    totals = {"processed": 0, "errors": 0, "batches": 0}
    for _ in range(max_batches):
        stats = pipeline.process_unprocessed(batch_size=batch_size)
        totals["processed"] += stats.get("processed", 0)
        totals["errors"] += stats.get("errors", 0)
        totals["batches"] += 1
        if stats.get("processed", 0) < batch_size:
            break
    return totals


def _add_ingest_stats(total: dict, stats: dict):
    total["total"] += stats.get("total", 0)
    total["checked"] += stats.get("checked", 0)
    total["new"] += stats.get("new", 0)
    total["duplicate"] += stats.get("duplicate", 0)
    total["duplicate_fuzzy"] += stats.get("duplicate_fuzzy", 0)
    total["error"] += stats.get("error", 0)
    if stats.get("stopped_early"):
        total["stopped_sources"] += 1


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
        return "rss_only" if stats.get("total", 0) else "no_links"
    if discovered_urls and known_urls == discovered_urls and scraped_count == 0:
        return "caught_up"
    if scraped_count == 0 and stats.get("total", 0):
        return "rss_only"
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


# ── Job: Send Subscriber Reports ─────────────────────────────────────

def job_send_reports(frequency: str):
    """Generate and send reports to subscribers of the given frequency."""
    if not SEND_EMAIL:
        logger.info("email_disabled, skipping report delivery")
        return

    session = SessionFactory()

    try:
        freq_enum = SubscriptionFrequency(frequency)
        subs = (
            session.query(Subscription)
            .filter(
                Subscription.is_active == True,
                Subscription.frequency == freq_enum,
            )
            .all()
        )

        if not subs:
            logger.info("no_subscribers", frequency=frequency)
            return

        logger.info("sending_reports", frequency=frequency, count=len(subs))

        # Group subscribers by country
        by_country: dict[str, list] = {}
        for sub in subs:
            by_country.setdefault(sub.country_code, []).append(sub)

        # Generate one report per country, send to all subscribers
        sender = EmailSender(
            smtp_host=settings.smtp_host,
            smtp_port=settings.smtp_port,
            smtp_user=settings.smtp_user,
            smtp_password=settings.smtp_password,
            sender_email=settings.sender_email,
        )

        days_map = {
            "daily": 1, "weekly": 7, "biweekly": 14, "monthly": 30
        }
        days = days_map.get(frequency, 7)

        for country_code, country_subs in by_country.items():
            country_name = COUNTRIES.get(country_code, {}).get(
                "name", country_code.upper()
            )

            config = ReportConfig(
                country_name=country_name,
                country_code=country_code,
                date_to=datetime.datetime.utcnow(),
                date_from=(
                    datetime.datetime.utcnow() - datetime.timedelta(days=days)
                ),
            )

            generator = PDFReportGenerator(session, settings.reports_dir)
            filepath = generator.generate(config)

            subject = (
                f"NewsIntel {frequency.capitalize()} Briefing — "
                f"{country_name} — {config.date_to.strftime('%B %d, %Y')}"
            )

            template_data = {
                "title": "News Intelligence Briefing",
                "subtitle": country_name,
                "frequency": frequency,
                "country": country_name,
                "date_range": (
                    f"{config.date_from.strftime('%B %d')} — "
                    f"{config.date_to.strftime('%B %d, %Y')}"
                ),
                "total_articles": 0,
                "total_sources": 0,
                "total_entities": 0,
                "categories": {},
                "pdf_attached": True,
                "unsubscribe_url": "#",
            }

            recipients = [
                {"email": s.email, "name": s.name or ""}
                for s in country_subs
            ]
            stats = sender.send_batch(
                recipients=recipients,
                subject=subject,
                template_data=template_data,
                pdf_path=filepath,
            )

            # Update last_sent_at
            for sub in country_subs:
                sub.last_sent_at = datetime.datetime.utcnow()
            session.commit()

            logger.info(
                "reports_sent",
                country=country_name,
                sent=stats["sent"],
                failed=stats["failed"],
            )

    except Exception as e:
        logger.error("report_delivery_failed", error=str(e))

    session.close()


# ── Job: Retrain ML model ────────────────────────────────────────────

def job_retrain_model():
    """Retrain the ML categorizer with accumulated labeled data."""
    session = SessionFactory()
    pipeline = ProcessingPipeline(
        session=session,
        enable_ai=False,
        model_path=settings.models_dir,
    )
    metrics = pipeline.train_categorizer(min_samples=100)
    if metrics:
        logger.info("model_retrained", **metrics)
    session.close()


# ── Main: Schedule all jobs ──────────────────────────────────────────

def main():
    global SEND_EMAIL, INSTANCE_LOCK

    parser = argparse.ArgumentParser(description="NewsIntel scheduler")
    parser.add_argument("--no-email", action="store_true")
    parser.add_argument("--country", default=None)
    parser.add_argument(
        "--interval-minutes",
        type=int,
        default=settings.ingestion_interval_minutes,
        help="Ingestion interval in minutes",
    )
    parser.add_argument(
        "--run-once",
        action="store_true",
        help="Run ingestion once, then exit",
    )
    parser.add_argument(
        "--skip-initial-run",
        action="store_true",
        help="Start the recurring clock without an immediate ingestion cycle",
    )
    args = parser.parse_args()

    SEND_EMAIL = settings.smtp_enabled and not args.no_email
    if not args.run_once:
        INSTANCE_LOCK = ProcessFileLock(settings.base_dir / "data" / "scheduler.lock")
        if not INSTANCE_LOCK.acquire():
            print("Another NewsIntel scheduler instance is already running.", file=sys.stderr)
            return 2
        atexit.register(INSTANCE_LOCK.release)
        _write_scheduler_pid()
        atexit.register(_clear_scheduler_pid)

    init()
    write_heartbeat("scheduler_started", country_code=args.country)

    scheduler = BlockingScheduler()

    # Ingest every hour
    scheduler.add_job(
        job_ingest_and_process,
        IntervalTrigger(minutes=args.interval_minutes),
        kwargs={"country_code": args.country},
        id="ingest",
        name="Article Ingestion",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300,
    )

    # Daily reports at 7:00 AM UTC
    scheduler.add_job(
        job_send_reports,
        CronTrigger(hour=7, minute=0),
        kwargs={"frequency": "daily"},
        id="daily_reports",
        name="Daily Report Delivery",
    )

    # Weekly reports on Monday at 7:00 AM UTC
    scheduler.add_job(
        job_send_reports,
        CronTrigger(day_of_week="mon", hour=7, minute=0),
        kwargs={"frequency": "weekly"},
        id="weekly_reports",
        name="Weekly Report Delivery",
    )

    # Monthly reports on 1st of month at 7:00 AM UTC
    scheduler.add_job(
        job_send_reports,
        CronTrigger(day=1, hour=7, minute=0),
        kwargs={"frequency": "monthly"},
        id="monthly_reports",
        name="Monthly Report Delivery",
    )

    # Retrain ML model weekly (Sunday midnight)
    scheduler.add_job(
        job_retrain_model,
        CronTrigger(day_of_week="sun", hour=0, minute=0),
        id="retrain",
        name="ML Model Retraining",
    )

    print("\nNewsIntel Scheduler Started")
    print("=" * 40)
    print(f"Countries: {', '.join(COUNTRIES.keys())}")
    print(f"Ingestion: every {args.interval_minutes} minutes")
    print(f"Email: {'enabled' if SEND_EMAIL else 'disabled'}")
    print(f"AI Summaries: {'enabled' if settings.enable_ai_summaries else 'disabled'}")
    print("=" * 40)
    print("\nPress Ctrl+C to stop.\n")

    try:
        result = None
        if not args.skip_initial_run:
            result = job_ingest_and_process(country_code=args.country)
        if args.run_once:
            if result and result.get("status") == "busy":
                print("Another ingestion or processing job is already running.", file=sys.stderr)
                return 2
            print("\nRun-once completed.")
            return
        # The initial run can take longer than the interval. Reset the recurring
        # trigger so the next cycle starts only after a full quiet interval.
        scheduler.reschedule_job(
            "ingest",
            trigger=IntervalTrigger(minutes=args.interval_minutes),
        )
        scheduler.start()
    except KeyboardInterrupt:
        print("\nShutting down scheduler...")
        scheduler.shutdown()


def _write_scheduler_pid():
    path = settings.base_dir / "data" / "scheduler.pid"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(os.getpid()), encoding="utf-8")


def _clear_scheduler_pid():
    path = settings.base_dir / "data" / "scheduler.pid"
    try:
        if path.exists() and path.read_text(encoding="utf-8").strip() == str(os.getpid()):
            path.unlink()
    except OSError:
        pass


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
