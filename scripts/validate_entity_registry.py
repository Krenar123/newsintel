#!/usr/bin/env python3
"""Validate the country entity registry before processing or deployment."""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.processing.entity_registry import EntityRegistry


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--path",
        type=Path,
        default=ROOT / "config" / "entities" / "north_macedonia.yaml",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    try:
        registry = EntityRegistry.load(args.path)
    except (OSError, ValueError) as exc:
        if args.json:
            print(json.dumps({"valid": False, "error": str(exc)}, ensure_ascii=False))
        else:
            print(f"INVALID: {exc}")
        return 1

    aliases = [alias for entity in registry.entities for alias in entity.aliases]
    report = {
        "valid": True,
        "country_code": registry.country_code,
        "entities": len(registry.entities),
        "aliases": len(aliases),
        "context_guarded_aliases": sum(
            bool(alias.requires_any or alias.excludes_any) for alias in aliases
        ),
        "review_only_aliases": sum(not alias.publishable for alias in aliases),
        "issues": registry.issues,
    }
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(
            f"VALID: {report['entities']} entities, {report['aliases']} aliases, "
            f"{report['context_guarded_aliases']} context guarded, "
            f"{report['review_only_aliases']} review only"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
