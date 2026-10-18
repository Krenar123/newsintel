#!/usr/bin/env python3
"""Evaluate conservative attacker/target/allegation extraction fixtures."""

import argparse
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.processing.attack_analysis import analyze_attack_text


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fixture",
        type=Path,
        default=ROOT / "tests" / "fixtures" / "attack_understanding_mk.yaml",
    )
    args = parser.parse_args()
    with args.fixture.open(encoding="utf-8") as handle:
        cases = (yaml.safe_load(handle) or {}).get("cases", [])

    failures = []
    for case in cases:
        result = analyze_attack_text(
            case.get("title", ""),
            case.get("content", ""),
            case.get("target", ""),
            case.get("aliases", []),
            case.get("candidates", []),
        )
        expected_attack = case.get("expect_attack", True)
        problems = []
        if result["is_attack"] != expected_attack:
            problems.append(f"is_attack={result['is_attack']} expected={expected_attack}")
        if case.get("expected_attacker") and result["attacker"] != case["expected_attacker"]:
            problems.append(f"attacker={result['attacker']} expected={case['expected_attacker']}")
        if case.get("expected_category") and case["expected_category"] not in result["categories"]:
            problems.append(f"missing category={case.get('expected_category')}")
        if case.get("expect_quote") and not result["quote"]:
            problems.append("missing quote")
        if problems:
            failures.append((case["id"], problems, result))

    for case_id, problems, result in failures:
        print(f"FAIL {case_id}: {'; '.join(problems)}")
        print(f"  result={result}")
    print(f"Attack understanding: {len(cases) - len(failures)}/{len(cases)} cases passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
