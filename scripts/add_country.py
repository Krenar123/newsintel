#!/usr/bin/env python3
"""
Add a new country configuration interactively.

Usage:
    python scripts/add_country.py

This walks you through creating a country config YAML file
with sources and RSS feeds.
"""

import sys
import re
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import yaml
from config import settings


def main():
    print("\n" + "=" * 60)
    print("  NewsIntel — Add New Country")
    print("=" * 60 + "\n")

    # Basic info
    name = input("Country name (e.g., Serbia): ").strip()
    code = input("Country code (e.g., rs): ").strip().lower()
    languages = input("Languages, comma-separated (e.g., sr,en): ").strip()
    timezone = input("Timezone (e.g., Europe/Belgrade): ").strip()

    languages = [l.strip() for l in languages.split(",")]

    # Sources
    sources = []
    print(f"\nNow add news sources for {name}.")
    print("For each source, provide its name, URL, and RSS feed URLs.")
    print("Type 'done' when finished adding sources.\n")

    while True:
        source_name = input("Source name (or 'done'): ").strip()
        if source_name.lower() == "done":
            break

        source_url = input(f"  Website URL for {source_name}: ").strip()
        source_lang = input(f"  Language ({'/'.join(languages)}): ").strip() or languages[0]
        reliability = input(f"  Reliability score (0.0-1.0, default 0.7): ").strip()
        reliability = float(reliability) if reliability else 0.7

        rss_feeds = []
        print(f"  Add RSS feeds for {source_name} (type 'done' when finished):")
        while True:
            feed_url = input("    RSS feed URL (or 'done'): ").strip()
            if feed_url.lower() == "done":
                break
            feed_cat = input("    Category (general/politics/economy/etc): ").strip() or "general"
            rss_feeds.append({"url": feed_url, "category": feed_cat})

        sources.append({
            "name": source_name,
            "url": source_url,
            "rss_feeds": rss_feeds,
            "language": source_lang,
            "reliability_score": reliability,
        })
        print(f"  ✓ Added {source_name} with {len(rss_feeds)} feeds\n")

    if not sources:
        print("No sources added. Aborting.")
        return

    # Build config
    config = {
        "name": name,
        "code": code,
        "languages": languages,
        "timezone": timezone,
        "sources": sources,
        "categories": [
            "politics", "economy", "society", "world",
            "sports", "tech", "culture", "crime",
            "health", "environment",
        ],
    }

    # Save
    filename = re.sub(r'[^a-z0-9]+', '_', name.lower()).strip('_')
    filepath = settings.countries_dir / f"{filename}.yaml"

    with open(filepath, "w") as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True)

    print(f"\n✓ Country config saved to: {filepath}")
    print(f"  {len(sources)} sources, "
          f"{sum(len(s['rss_feeds']) for s in sources)} feeds")
    print(f"\nNext steps:")
    print(f"  1. Verify the config: cat {filepath}")
    print(f"  2. Seed sources: python scripts/setup_db.py --seed")
    print(f"  3. Run ingestion: python scripts/ingest.py --country {code} --process")


if __name__ == "__main__":
    main()
