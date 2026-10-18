#!/usr/bin/env python3
"""Plan a bounded historical ingestion run.

This is intentionally a planner, not a crawler. Historical backfills can create
many duplicates and low-quality pages, so this tool first shows source coverage,
archive readiness, and safe next actions before any large fetch is attempted.
"""

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import yaml
from sqlalchemy import func, or_

from config import settings
from src.models.database import Article, Source, create_all_tables, get_engine, get_session_factory


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Plan historical ingestion safely")
    parser.add_argument("--country", default=settings.default_country)
    parser.add_argument("--date-from", default="2010-01-01")
    parser.add_argument("--date-to", default=dt.date.today().isoformat())
    parser.add_argument("--target-per-source", type=int, default=1000)
    parser.add_argument("--max-per-run", type=int, default=250)
    parser.add_argument("--duplicate-stop", type=int, default=settings.stop_after_consecutive_duplicates)
    parser.add_argument("--include-inactive", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    date_from = _parse_date(args.date_from)
    date_to = _parse_date(args.date_to) + dt.timedelta(days=1)
    country_config = _load_country_config(args.country)

    engine = get_engine(settings.database_url)
    create_all_tables(engine)
    Session = get_session_factory(engine)
    session = Session()
    try:
        rows = []
        for source_config in country_config.get("sources", []):
            if source_config.get("is_active", True) is False and not args.include_inactive:
                continue
            row = _source_plan(
                session=session,
                source_config=source_config,
                country_code=country_config.get("code", args.country),
                date_from=date_from,
                date_to=date_to,
                target_per_source=args.target_per_source,
                max_per_run=args.max_per_run,
                duplicate_stop=args.duplicate_stop,
            )
            rows.append(row)
    finally:
        session.close()
        engine.dispose()

    summary = {
        "country_code": country_config.get("code", args.country),
        "date_from": date_from.date().isoformat(),
        "date_to": (date_to - dt.timedelta(days=1)).date().isoformat(),
        "source_count": len(rows),
        "archive_ready": len([row for row in rows if row["archive_ready"]]),
        "needs_archive_config": len([row for row in rows if row["status"] == "needs_archive_config"]),
        "already_at_target": len([row for row in rows if row["status"] == "at_target"]),
        "target_per_source": args.target_per_source,
        "max_per_run": args.max_per_run,
        "duplicate_stop": args.duplicate_stop,
    }
    payload = {"summary": summary, "sources": rows}
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    else:
        _print_table(payload)
    return 0


def _source_plan(
    session,
    source_config: dict,
    country_code: str,
    date_from: dt.datetime,
    date_to: dt.datetime,
    target_per_source: int,
    max_per_run: int,
    duplicate_stop: int,
) -> dict:
    source_name = source_config.get("name") or "Unknown"
    source_url = source_config.get("url") or ""
    scraper_cfg = source_config.get("scraper") or {}
    archive_config = scraper_cfg.get("archive") or {}
    archive_urls = scraper_cfg.get("archive_urls") or scraper_cfg.get("archive_listing_urls") or []
    if archive_config.get("enabled") and archive_config.get("endpoint"):
        archive_urls = [archive_config["endpoint"], *archive_urls]
    source = (
        session.query(Source)
        .filter(
            Source.country_code == country_code,
            or_(Source.name == source_name, Source.url == source_url),
        )
        .first()
    )
    article_count = 0
    latest = None
    earliest = None
    if source:
        date_column = func.coalesce(Article.published_at, Article.fetched_at, Article.ingested_at)
        stats = (
            session.query(
                func.count(Article.id),
                func.min(date_column),
                func.max(date_column),
            )
            .filter(Article.source_id == source.id)
            .filter(date_column >= date_from, date_column < date_to)
            .first()
        )
        article_count = int(stats[0] or 0)
        earliest = stats[1].isoformat() if stats and stats[1] else None
        latest = stats[2].isoformat() if stats and stats[2] else None

    gap = max(0, target_per_source - article_count)
    archive_ready = bool(archive_urls)
    if gap == 0:
        status = "at_target"
    elif archive_ready:
        status = "ready_for_bounded_backfill"
    elif scraper_cfg.get("enabled"):
        status = "needs_archive_config"
    else:
        status = "no_direct_scraper"

    recommended_batch = min(gap or max_per_run, max_per_run)
    next_action = _next_action(
        country_code=country_code,
        source_name=source_name,
        status=status,
        recommended_batch=recommended_batch,
        duplicate_stop=duplicate_stop,
    )
    return {
        "source_name": source_name,
        "source_url": source_url,
        "rss_enabled": bool(source_config.get("rss_enabled", True)),
        "scraper_enabled": bool(scraper_cfg.get("enabled")),
        "archive_ready": archive_ready,
        "archive_url_count": len(archive_urls),
        "stored_articles_in_range": article_count,
        "earliest_stored": earliest,
        "latest_stored": latest,
        "target_gap": gap,
        "recommended_batch": recommended_batch,
        "status": status,
        "next_action": next_action,
    }


def _next_action(
    country_code: str,
    source_name: str,
    status: str,
    recommended_batch: int,
    duplicate_stop: int,
) -> str:
    if status == "at_target":
        return "No backfill needed for this target."
    if status == "ready_for_bounded_backfill":
        return (
            "Run a future bounded archive fetch for this source with "
            f"max_articles={recommended_batch} and duplicate_stop={duplicate_stop}."
        )
    if status == "needs_archive_config":
        return (
            "Add scraper.archive_urls/archive selectors for this source before historical backfill; "
            f"use live ingestion meanwhile: .\\venv\\Scripts\\python.exe scripts\\ingest.py --country {country_code} --process --stop-after-duplicates {duplicate_stop}"
        )
    return f"Use RSS/live ingestion only unless a direct scraper is re-enabled for {source_name}."


def _load_country_config(country_code: str) -> dict:
    code_to_file = {"mk": "north_macedonia"}
    config_name = code_to_file.get(country_code, country_code)
    path = settings.countries_dir / f"{config_name}.yaml"
    if not path.exists():
        raise SystemExit(f"Country config not found: {path}")
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _parse_date(value: str) -> dt.datetime:
    return dt.datetime.strptime(value, "%Y-%m-%d")


def _print_table(payload: dict) -> None:
    summary = payload["summary"]
    print(
        f"Historical ingestion plan for {summary['country_code']} "
        f"{summary['date_from']}..{summary['date_to']}"
    )
    print(
        f"Sources: {summary['source_count']} | archive-ready: {summary['archive_ready']} | "
        f"need archive config: {summary['needs_archive_config']} | at target: {summary['already_at_target']}"
    )
    print("Source | Stored | Gap | Archive | Status | Next")
    print("-" * 150)
    for row in payload["sources"]:
        print(
            " | ".join([
                row["source_name"][:24],
                str(row["stored_articles_in_range"]),
                str(row["target_gap"]),
                "yes" if row["archive_ready"] else "no",
                row["status"],
                row["next_action"][:70],
            ])
        )


if __name__ == "__main__":
    raise SystemExit(main())
