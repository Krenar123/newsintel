#!/usr/bin/env python3
"""Build cross-source story clusters for validation/trust signals."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import settings
from src.models.database import create_all_tables, get_engine, get_session_factory
from src.processing.story_clustering import StoryClusterer


def main():
    parser = argparse.ArgumentParser(description="Cluster articles into same-story groups")
    parser.add_argument("--country", default="mk")
    parser.add_argument("--days", type=int, default=14)
    parser.add_argument("--limit", type=int, default=1000)
    args = parser.parse_args()

    engine = get_engine(settings.database_url)
    create_all_tables(engine)
    Session = get_session_factory(engine)
    session = Session()
    try:
        stats = StoryClusterer(session).rebuild(
            country_code=args.country,
            days=args.days,
            limit=args.limit,
        )
        print("Story clustering complete")
        print(f"  Articles considered: {stats['articles_considered']}")
        print(f"  Clusters created:    {stats['clusters_created']}")
        print(f"  Article links:       {stats['cluster_links']}")
        print(f"  Title comparisons:   {stats['title_comparisons']}")
    finally:
        session.close()
        engine.dispose()


if __name__ == "__main__":
    main()
