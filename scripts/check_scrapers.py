#!/usr/bin/env python3
"""Check scraper health for configured country sources."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import yaml

from config import settings
from src.ingestion.scraper import ArticleScraper


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Check scraper health")
    parser.add_argument("--country", default=settings.default_country)
    parser.add_argument("--source", default="", help="Only check sources containing this text")
    parser.add_argument("--max-articles", type=int, default=3)
    parser.add_argument("--json", action="store_true", help="Print JSON instead of a table")
    parser.add_argument(
        "--fail-on-problems",
        action="store_true",
        help="Exit non-zero when active scrapers are degraded/failing/no_links/error",
    )
    args = parser.parse_args()

    config = _load_country_config(args.country)
    rows = []
    for source in config.get("sources", []):
        if args.source and args.source.lower() not in source.get("name", "").lower():
            continue
        source = {**source, "country_code": config.get("code", args.country)}
        rows.append(check_source(source, args.max_articles))

    if args.json:
        print(json.dumps(rows, indent=2, ensure_ascii=False, default=str))
    else:
        _print_table(rows)
    if args.fail_on_problems and any(_is_problem(row) for row in rows):
        return 1
    return 0


def check_source(source: dict, max_articles: int) -> dict:
    scraper_cfg = source.get("scraper") or {}
    row = {
        "source_name": source.get("name"),
        "source_url": source.get("url"),
        "scraper_enabled": bool(scraper_cfg.get("enabled")),
        "discovered_urls": 0,
        "success_count": 0,
        "failed_count": 0,
        "average_word_count": 0,
        "minimum_average_word_count": int(scraper_cfg.get("preflight_min_average_words", 100)),
        "published_date_count": 0,
        "author_count": 0,
        "image_count": 0,
        "status": "disabled" if not scraper_cfg.get("enabled") else "unknown",
        "error_sample": None,
        "sample_urls": [],
        "failed_urls": [],
        "failure_details": [],
        "min_word_count": 0,
        "max_word_count": 0,
        "suggested_fix": None,
    }
    if not scraper_cfg.get("enabled"):
        return row

    scraper = ArticleScraper(delay_seconds=0, max_articles_per_source=max_articles)
    try:
        urls = scraper.discover_article_urls(source)
        row["discovered_urls"] = len(urls)
        row["sample_urls"] = urls[:max_articles]
        word_counts = []
        for url in urls[:max_articles]:
            result = scraper.scrape_article(url, scraper_cfg)
            if result.success:
                row["success_count"] += 1
                word_counts.append(result.word_count)
                row["published_date_count"] += int(result.published_at is not None)
                row["author_count"] += int(bool(result.author))
                row["image_count"] += int(bool(result.image_url))
            else:
                row["failed_count"] += 1
                row["error_sample"] = row["error_sample"] or result.error
                row["failed_urls"].append(url)
                row["failure_details"].append({
                    "url": url,
                    "error": result.error,
                    "title": result.title,
                    "word_count": result.word_count,
                })
        if word_counts:
            row["average_word_count"] = round(sum(word_counts) / len(word_counts), 1)
            row["min_word_count"] = min(word_counts)
            row["max_word_count"] = max(word_counts)
        row["status"] = _status(row)
        row["suggested_fix"] = _suggested_fix(row)
        return row
    except Exception as exc:
        row["status"] = "error"
        row["error_sample"] = str(exc)
        row["suggested_fix"] = _suggested_fix(row)
        return row
    finally:
        scraper.close()


def _status(row: dict) -> str:
    if row["discovered_urls"] == 0:
        return "no_links"
    if row["success_count"] == 0:
        return "failing"
    checked = row["success_count"] + row["failed_count"]
    failure_rate = row["failed_count"] / checked if checked else 0
    if row["failed_count"] > row["success_count"] or failure_rate >= 0.25:
        return "degraded"
    if row["published_date_count"] < row["success_count"]:
        return "degraded"
    if (
        row["average_word_count"]
        and row["average_word_count"] < row.get("minimum_average_word_count", 100)
    ):
        return "degraded"
    return "healthy"


def _suggested_fix(row: dict) -> str:
    if row["status"] == "disabled":
        return "No action unless this source should be re-enabled."
    if row["status"] == "no_links":
        return "Check listing_urls, article_link_selectors, source availability, or network access."
    if row["status"] == "failing":
        return "Inspect failed_urls and update body/title/date selectors or URL filters."
    if row["status"] == "degraded":
        if row.get("published_date_count", 0) < row.get("success_count", 0):
            return "Publication dates are missing; update the date selector before trusting scheduled ingestion."
        if row.get("error_sample") == "low_word_count":
            return "Check whether short articles are legitimate; if yes, lower min_word_count for this source only."
        if row.get("error_sample") == "low_unique_word_count":
            return "Check whether repeated/short wire items are legitimate; if yes, lower min_unique_words for this source only."
        if (
            row.get("average_word_count", 0)
            and row["average_word_count"] < row.get("minimum_average_word_count", 100)
        ):
            return "Review whether short articles are legitimate; tune preflight_min_average_words only for this source."
        return "Review failure_details and failed_urls; update selectors or exclude non-article links."
    if row["status"] == "error":
        return "Check scraper exception, SSL/network access, and source config."
    return "No action."


def _is_problem(row: dict) -> bool:
    return bool(row.get("scraper_enabled")) and row.get("status") in {
        "degraded",
        "failing",
        "no_links",
        "error",
    }


def _load_country_config(country_code: str) -> dict:
    code_to_file = {"mk": "north_macedonia"}
    config_name = code_to_file.get(country_code, country_code)
    path = settings.countries_dir / f"{config_name}.yaml"
    if not path.exists():
        raise SystemExit(f"Country config not found: {path}")
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _print_table(rows: list[dict]) -> None:
    headers = ["Source", "Links", "OK", "Fail", "Avg Words", "Min", "Status", "Error", "Suggested Fix"]
    print(" | ".join(headers))
    print("-" * 140)
    for row in rows:
        print(
            " | ".join([
                str(row["source_name"])[:24],
                str(row["discovered_urls"]),
                str(row["success_count"]),
                str(row["failed_count"]),
                str(row["average_word_count"]),
                str(row["min_word_count"]),
                row["status"],
                str(row.get("error_sample") or "")[:32],
                str(row.get("suggested_fix") or "")[:52],
            ])
        )


if __name__ == "__main__":
    raise SystemExit(main())
