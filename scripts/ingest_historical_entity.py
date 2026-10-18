#!/usr/bin/env python3
"""Bounded historical ingestion for a named entity via configured archives.

The command is dry-run by default. It only supports sources explicitly marked
archive.enabled in the country YAML and requires backup confirmation to write.
"""

import argparse
import datetime as dt
import html
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx
import yaml
from bs4 import BeautifulSoup
from dateutil import parser as dateparser

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import settings
from src.ingestion.rss_fetcher import RawArticle, _certifi_verify, normalize_url
from src.ingestion.scraper import ArticleScraper
from src.models.database import Article, Source, create_all_tables, get_engine, get_session_factory
from src.processing.pipeline import ProcessingPipeline
from src.operations.process_lock import ProcessFileLock


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(
        description="Ingest a bounded historical archive slice for one entity or party"
    )
    parser.add_argument("--entity", required=True, help="Person/party search phrase")
    parser.add_argument("--query", default="", help="Archive search phrase; defaults to --entity")
    parser.add_argument("--country", default="mk")
    parser.add_argument("--source", action="append", default=[], help="Exact source name; repeatable")
    parser.add_argument("--date-from", required=True)
    parser.add_argument("--date-to", default=dt.date.today().isoformat())
    parser.add_argument("--max-per-source", type=int, default=25)
    parser.add_argument("--page-start", type=int, default=1)
    parser.add_argument(
        "--duplicate-stop",
        type=int,
        default=settings.stop_after_consecutive_duplicates,
    )
    parser.add_argument("--delay", type=float, default=0.35)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--process", action="store_true")
    parser.add_argument(
        "--confirm-backup",
        action="store_true",
        help="Required with --apply after confirming a current database backup",
    )
    args = parser.parse_args()

    if args.max_per_source < 1 or args.max_per_source > 100:
        raise SystemExit("--max-per-source must be between 1 and 100")
    if args.page_start < 1:
        raise SystemExit("--page-start must be at least 1")
    if args.apply and not args.confirm_backup:
        raise SystemExit("Refusing historical writes without --confirm-backup")

    date_from = _parse_day(args.date_from)
    date_to = _parse_day(args.date_to) + dt.timedelta(days=1)
    if date_from >= date_to:
        raise SystemExit("--date-from must be before --date-to")

    country_config = _load_country_config(args.country)
    source_configs = _archive_sources(country_config, args.source)
    if not source_configs:
        raise SystemExit("No matching archive-enabled sources were found")

    operation_lock = None
    if args.apply:
        operation_lock = ProcessFileLock(settings.base_dir / "data" / "ingestion_job.lock")
        if not operation_lock.acquire():
            raise SystemExit("Another ingestion or historical job is already running")

    engine = get_engine(settings.database_url)
    create_all_tables(engine)
    session = get_session_factory(engine)()
    http_client = httpx.Client(
        timeout=30,
        follow_redirects=True,
        verify=_certifi_verify(),
        headers={"User-Agent": "NewsIntel/1.0 historical archive research"},
    )
    scraper = ArticleScraper(delay_seconds=args.delay)
    phrase = (args.query or args.entity).strip()
    totals = {
        "sources": 0,
        "source_errors": 0,
        "discovered": 0,
        "existing": 0,
        "scraped": 0,
        "new": 0,
    }

    try:
        for source_config in source_configs:
            totals["sources"] += 1
            archive = source_config["scraper"]["archive"]
            try:
                posts, available = _wordpress_posts(
                    http_client=http_client,
                    endpoint=archive["endpoint"],
                    phrase=phrase,
                    date_from=date_from,
                    date_to=date_to,
                    limit=args.max_per_source,
                    page_start=args.page_start,
                )
            except (httpx.HTTPError, RuntimeError, ValueError) as exc:
                totals["source_errors"] += 1
                print(
                    f"{source_config['name']}: archive_error="
                    f"{type(exc).__name__}: {str(exc)[:220]}"
                )
                continue
            links = []
            for post in posts:
                link = normalize_url(post.get("link") or "")
                if link and link not in links:
                    links.append(link)
            existing_urls = {
                url
                for (url,) in session.query(Article.url).filter(Article.url.in_(links)).all()
            } if links else set()
            new_posts = [post for post in posts if normalize_url(post.get("link") or "") not in existing_urls]
            totals["discovered"] += len(posts)
            totals["existing"] += len(posts) - len(new_posts)

            dates = [post.get("date_gmt") or post.get("date") for post in posts]
            dates = [value for value in dates if value]
            print(
                f"{source_config['name']}: archive_matches={available} page_items={len(posts)} "
                f"existing={len(posts) - len(new_posts)} new_candidates={len(new_posts)} "
                f"range={min(dates) if dates else '-'}..{max(dates) if dates else '-'}"
            )
            for post in new_posts[:5]:
                print(
                    f"  {post.get('date_gmt') or post.get('date') or '-'} | "
                    f"{_plain_title(post)[:100]} | {post.get('link')}"
                )

            if not args.apply or not new_posts:
                continue

            raw_articles = []
            consecutive_existing = 0
            for post in posts:
                link = normalize_url(post.get("link") or "")
                if not link:
                    continue
                if link in existing_urls:
                    consecutive_existing += 1
                    if consecutive_existing >= args.duplicate_stop:
                        print(
                            f"  stopped after {consecutive_existing} consecutive stored URLs"
                        )
                        break
                    continue
                consecutive_existing = 0
                result = scraper.scrape_article(link, source_config.get("scraper") or {})
                if not result.success:
                    print(f"  scrape failed: {result.error} | {link}")
                    continue
                published_at = _post_date(post) or result.published_at
                raw = RawArticle(
                    url=result.url,
                    title=result.title or _plain_title(post),
                    content=result.content,
                    author=result.author,
                    published_at=published_at,
                    language=source_config.get("language", "mk"),
                    source_name=source_config["name"],
                    source_url=source_config.get("url", ""),
                    source_country_code=country_config.get("code", args.country),
                    source_type=source_config.get("source_type", "news"),
                    source_reliability_score=float(source_config.get("reliability_score", 0.5)),
                    source_political_leaning=source_config.get("political_leaning", "unknown"),
                    source_ownership=source_config.get("ownership"),
                    image_url=result.image_url,
                    raw_html=result.html,
                    ingestion_method="historical_scrape",
                )
                raw.compute_hash()
                raw_articles.append(raw)

            pipeline = ProcessingPipeline(session, languages=["mk", "en", "sq"])
            ingestion = pipeline.ingest_articles(
                raw_articles,
                stop_after_consecutive_duplicates=args.duplicate_stop,
            )
            totals["scraped"] += len(raw_articles)
            totals["new"] += ingestion.get("new", 0)
            print(
                f"  applied: scraped={len(raw_articles)} new={ingestion.get('new', 0)} "
                f"duplicate={ingestion.get('duplicate', 0)} fuzzy={ingestion.get('duplicate_fuzzy', 0)}"
            )

        if args.apply and args.process:
            pipeline = ProcessingPipeline(session, languages=["mk", "en", "sq"])
            remaining = totals["new"]
            while remaining > 0:
                batch = pipeline.process_unprocessed(batch_size=min(100, remaining))
                processed = int(batch.get("processed", 0))
                if processed == 0:
                    break
                remaining -= processed

        mode = "APPLIED" if args.apply else "DRY RUN"
        print(
            f"{mode}: entity={args.entity!r} query={phrase!r} sources={totals['sources']} "
            f"source_errors={totals['source_errors']} "
            f"discovered={totals['discovered']} existing={totals['existing']} "
            f"scraped={totals['scraped']} new={totals['new']}"
        )
        return 1 if totals["source_errors"] >= totals["sources"] else 0
    finally:
        scraper.close()
        http_client.close()
        session.close()
        engine.dispose()
        if operation_lock is not None:
            operation_lock.release()


def _wordpress_posts(
    http_client: httpx.Client,
    endpoint: str,
    phrase: str,
    date_from: dt.datetime,
    date_to: dt.datetime,
    limit: int,
    page_start: int,
) -> tuple[list[dict], int]:
    params = {
        "search": phrase,
        "after": date_from.isoformat(),
        "before": date_to.isoformat(),
        "orderby": "date",
        "order": "asc",
        "per_page": limit,
        "page": page_start,
        "_fields": "id,date,date_gmt,link,title",
    }
    response = None
    last_error = None
    for attempt in range(3):
        try:
            response = http_client.get(endpoint, params=params)
            response.raise_for_status()
            break
        except httpx.HTTPError as exc:
            last_error = exc
            response = None
            if "CERTIFICATE_VERIFY_FAILED" in str(exc):
                with httpx.Client(
                    timeout=30,
                    follow_redirects=True,
                    verify=False,
                    headers=http_client.headers,
                ) as insecure_client:
                    response = insecure_client.get(endpoint, params=params)
                    response.raise_for_status()
                break
            if attempt < 2:
                time.sleep(1.5 * (attempt + 1))
    if response is None:
        raise last_error or RuntimeError(f"Archive request failed: {endpoint}")
    payload = response.json()
    if not isinstance(payload, list):
        raise RuntimeError(f"Unexpected archive response from {urlparse(endpoint).netloc}")
    return payload, int(response.headers.get("X-WP-Total", len(payload)))


def _archive_sources(country_config: dict, names: list[str]) -> list[dict]:
    requested = set(names)
    rows = []
    for source in country_config.get("sources", []):
        archive = (source.get("scraper") or {}).get("archive") or {}
        if not archive.get("enabled") or archive.get("method") != "wordpress_api":
            continue
        if requested and source.get("name") not in requested:
            continue
        rows.append(source)
    missing = requested - {source.get("name") for source in rows}
    if missing:
        raise SystemExit(f"Archive source not configured: {', '.join(sorted(missing))}")
    return rows


def _plain_title(post: dict) -> str:
    rendered = (post.get("title") or {}).get("rendered", "")
    return BeautifulSoup(html.unescape(rendered), "lxml").get_text(" ", strip=True)


def _post_date(post: dict) -> dt.datetime | None:
    raw = post.get("date_gmt") or post.get("date")
    if not raw:
        return None
    parsed = dateparser.parse(raw)
    return parsed.replace(tzinfo=None) if parsed and parsed.tzinfo else parsed


def _parse_day(value: str) -> dt.datetime:
    return dt.datetime.strptime(value, "%Y-%m-%d")


def _load_country_config(country_code: str) -> dict:
    name = {"mk": "north_macedonia"}.get(country_code, country_code)
    path = settings.countries_dir / f"{name}.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


if __name__ == "__main__":
    raise SystemExit(main())
