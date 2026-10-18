#!/usr/bin/env python3
"""Plan or run bounded, year-by-year historical political backfills."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config import settings


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Run the configured political history campaign")
    parser.add_argument("--entity", action="append", default=[], help="Subject key; repeatable")
    parser.add_argument("--year", type=int, help="Run only one year")
    parser.add_argument("--from-year", type=int)
    parser.add_argument("--to-year", type=int, default=dt.date.today().year)
    parser.add_argument("--max-per-source", type=int)
    parser.add_argument("--source", action="append", default=[])
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--process", action="store_true")
    parser.add_argument("--confirm-backup", action="store_true")
    parser.add_argument("--continue-on-error", action="store_true")
    args = parser.parse_args()

    if args.apply and not args.confirm_backup:
        raise SystemExit("Refusing campaign writes without --confirm-backup")

    config_path = settings.base_dir / "config" / "historical" / "north_macedonia.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    subjects = config.get("subjects") or []
    requested = set(args.entity)
    if requested:
        subjects = [item for item in subjects if item.get("key") in requested]
        missing = requested - {item.get("key") for item in subjects}
        if missing:
            raise SystemExit(f"Unknown campaign subject(s): {', '.join(sorted(missing))}")

    max_per_source = args.max_per_source or int(config.get("default_max_per_source", 25))
    campaign_rows = []
    for subject in subjects:
        first_year = args.year or max(args.from_year or subject["from_year"], subject["from_year"])
        last_year = args.year or args.to_year
        for year in range(first_year, last_year + 1):
            campaign_rows.append((subject, year))

    mode = "APPLY" if args.apply else "DRY RUN"
    print(f"{mode}: {len(subjects)} subjects, {len(campaign_rows)} yearly slices")
    print("Writes require both --apply and --confirm-backup.")
    failures = 0
    completed = 0
    for index, (subject, year) in enumerate(campaign_rows, start=1):
        date_to = dt.date(year, 12, 31)
        if year == dt.date.today().year:
            date_to = dt.date.today()
        command = [
            sys.executable,
            str(ROOT / "scripts" / "ingest_historical_entity.py"),
            "--entity", subject["name"],
            "--query", subject["query"],
            "--country", config.get("country", "mk"),
            "--date-from", f"{year}-01-01",
            "--date-to", date_to.isoformat(),
            "--max-per-source", str(max_per_source),
        ]
        for source in args.source:
            command.extend(["--source", source])
        if args.apply:
            command.extend(["--apply", "--confirm-backup"])
        if args.process:
            command.append("--process")

        print(f"\n[{index}/{len(campaign_rows)}] {subject['name']} | {year}")
        result = subprocess.run(command, cwd=ROOT, check=False)
        status = "completed" if result.returncode == 0 else "failed"
        _append_ledger({
            "subject_key": subject["key"],
            "subject_name": subject["name"],
            "year": year,
            "mode": mode.lower().replace(" ", "_"),
            "status": status,
            "return_code": result.returncode,
            "recorded_at": dt.datetime.utcnow().isoformat() + "Z",
        })
        if result.returncode:
            failures += 1
            if not args.continue_on_error:
                break
        else:
            completed += 1

    print(f"\nCampaign result: completed={completed} failed={failures}")
    return 1 if failures else 0


def _append_ledger(row: dict) -> None:
    path = settings.base_dir / "data" / "historical_campaign.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
