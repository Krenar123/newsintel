#!/usr/bin/env python3
"""Check TIME.mk aggregator story-spread parsing.

TIME.mk is treated as a validation/spread layer, not as an original publisher.
This script verifies that we can read clusters and source mentions from the
front page without ingesting TIME pages as articles.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.ingestion.time_mk import TimeMkAggregator


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Check TIME.mk aggregator parsing")
    parser.add_argument("--path", default="/", help="TIME.mk path to inspect")
    parser.add_argument("--limit", type=int, default=20, help="Number of clusters to print")
    parser.add_argument("--json", action="store_true", help="Print JSON instead of a table")
    parser.add_argument(
        "--fail-on-empty",
        action="store_true",
        help="Exit non-zero when no clusters or article references are found",
    )
    args = parser.parse_args()

    aggregator = TimeMkAggregator()
    try:
        stories = aggregator.fetch_front_page(args.path)
    finally:
        aggregator.close()

    rows = [_story_row(story) for story in stories[: args.limit]]

    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    else:
        _print_table(rows)

    if args.fail_on_empty and (not rows or not any(row["article_count"] for row in rows)):
        return 1
    return 0


def _story_row(story) -> dict:
    return {
        "cluster_id": story.cluster_id,
        "title": story.title,
        "reported_count": story.reported_count,
        "source_count": story.source_count,
        "article_count": len(story.articles),
        "sources": story.source_names[:8],
        "story_url": story.story_url,
        "summary_url": story.summary_url,
        "related_topics_url": story.related_topics_url,
        "articles": [
            {
                "title": article.title,
                "url": article.url,
                "source_name": article.source_name,
                "source_slug": article.source_slug,
            }
            for article in story.articles[:5]
        ],
    }


def _print_table(rows: list[dict]) -> None:
    headers = ["Cluster", "Reported", "Refs", "Sources", "Title", "Source Names"]
    print(" | ".join(headers))
    print("-" * 140)
    for row in rows:
        sources = ", ".join(row["sources"])[:42]
        print(
            " | ".join([
                row["cluster_id"][:12],
                str(row["reported_count"] or ""),
                str(row["article_count"]),
                str(row["source_count"]),
                row["title"][:54],
                sources,
            ])
        )


if __name__ == "__main__":
    raise SystemExit(main())
