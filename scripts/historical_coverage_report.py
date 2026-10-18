#!/usr/bin/env python3
"""Report year-by-year stored coverage for configured political subjects."""

import argparse
import datetime
import json
import sys
from pathlib import Path

import yaml
from sqlalchemy import extract, func, or_

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import settings
from src.models.database import Article, create_all_tables, get_engine, get_session_factory
from src.search.predicates import article_text_match


def main() -> int:
    parser = argparse.ArgumentParser(description="Report historical subject coverage")
    parser.add_argument(
        "--config",
        default="config/historical/north_macedonia.yaml",
    )
    parser.add_argument("--to-year", type=int, default=datetime.datetime.utcnow().year)
    parser.add_argument("--minimum-per-year", type=int, default=10)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    config = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    engine = get_engine(settings.database_url)
    create_all_tables(engine)
    session_factory = get_session_factory(engine)
    rows = []
    with session_factory() as db:
        for subject in config.get("subjects", []):
            terms = [
                subject.get("query"),
                subject.get("name"),
                *(subject.get("aliases") or []),
            ]
            terms = list(dict.fromkeys(term for term in terms if term))
            match = article_text_match(db, terms)
            year_expr = extract("year", Article.published_at)
            query = (
                db.query(year_expr.label("year"), func.count(Article.id))
                .filter(
                    Article.published_at.isnot(None),
                    or_(
                        Article.quality_status.is_(None),
                        Article.quality_status != "excluded",
                    ),
                )
                .group_by(year_expr)
            )
            if match is not None:
                query = query.filter(match)
            counts = {int(year): count for year, count in query.all()}
            from_year = int(subject.get("from_year", args.to_year))
            years = list(range(from_year, args.to_year + 1))
            gaps = [
                year
                for year in years
                if counts.get(year, 0) < args.minimum_per_year
            ]
            rows.append({
                "key": subject["key"],
                "name": subject["name"],
                "from_year": from_year,
                "to_year": args.to_year,
                "minimum_per_year": args.minimum_per_year,
                "counts": {str(year): counts.get(year, 0) for year in years},
                "years_ready": len(years) - len(gaps),
                "years_total": len(years),
                "gap_years": gaps,
                "total_matching_articles": sum(counts.get(year, 0) for year in years),
            })
    engine.dispose()

    result = {
        "database": engine.dialect.name,
        "minimum_per_year": args.minimum_per_year,
        "subjects": rows,
        "complete_subjects": sum(not row["gap_years"] for row in rows),
        "subject_count": len(rows),
    }
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8")
        print("subject | ready years | matching articles | first gaps")
        for row in rows:
            gaps = ", ".join(map(str, row["gap_years"][:8])) or "none"
            print(
                f"{row['key']:<24} | "
                f"{row['years_ready']:>2}/{row['years_total']:<2} | "
                f"{row['total_matching_articles']:>6} | {gaps}"
            )
        print(
            f"\nComplete subjects: {result['complete_subjects']}/"
            f"{result['subject_count']} at {args.minimum_per_year} articles/year"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
