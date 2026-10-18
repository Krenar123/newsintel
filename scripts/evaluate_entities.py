#!/usr/bin/env python3
"""Evaluate the entity extractor against a curated MK/SQ acceptance set."""

import argparse
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.processing.entities import EntityExtractor


DEFAULT_FIXTURE = ROOT / "tests" / "fixtures" / "entity_quality_mk.yaml"


def _key(name: str, entity_type: str) -> tuple[str, str]:
    return EntityExtractor._canonicalize(name), entity_type


def evaluate(fixture_path: Path) -> dict:
    with fixture_path.open(encoding="utf-8") as handle:
        fixture = yaml.safe_load(handle) or {}

    cases = fixture.get("cases", [])
    extractor = EntityExtractor(languages=["mk", "sq", "en"])
    totals = {
        "cases": len(cases),
        "expected": 0,
        "true_positive": 0,
        "false_positive": 0,
        "missing": 0,
        "wrong_type": 0,
        "forbidden": 0,
    }
    case_results = []

    for case in cases:
        result = extractor.extract(
            str(case.get("text", "")),
            language=str(case.get("language", "mk")),
            max_entities=100,
        )
        actual = {(entity.canonical_name, entity.entity_type) for entity in result.entities}
        expected = {
            _key(str(item["name"]), str(item["type"]))
            for item in case.get("expected", [])
        }
        expected_names = {name for name, _ in expected}
        actual_names = {name for name, _ in actual}
        forbidden_names = {
            EntityExtractor._canonicalize(str(name))
            for name in case.get("forbidden", [])
        }

        true_positive = actual & expected
        missing = expected - actual
        wrong_type = {
            (name, actual_type, expected_type)
            for name, expected_type in missing
            for actual_name, actual_type in actual
            if actual_name == name
        }
        unexpected = {
            pair for pair in actual
            if pair[0] not in expected_names
        }
        forbidden = actual_names & forbidden_names

        totals["expected"] += len(expected)
        totals["true_positive"] += len(true_positive)
        totals["missing"] += len(missing)
        totals["wrong_type"] += len(wrong_type)
        totals["false_positive"] += len(unexpected)
        totals["forbidden"] += len(forbidden)

        case_results.append({
            "id": case.get("id", "unnamed"),
            "passed": not missing and not unexpected and not forbidden,
            "missing": sorted(f"{name} [{kind}]" for name, kind in missing),
            "wrong_type": sorted(
                f"{name} [{actual_type}, expected {expected_type}]"
                for name, actual_type, expected_type in wrong_type
            ),
            "unexpected": sorted(f"{name} [{kind}]" for name, kind in unexpected),
            "forbidden": sorted(forbidden),
        })

    recall = (
        totals["true_positive"] / totals["expected"]
        if totals["expected"] else 1.0
    )
    precision_denominator = totals["true_positive"] + totals["false_positive"]
    precision = (
        totals["true_positive"] / precision_denominator
        if precision_denominator else 1.0
    )
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision + recall else 0.0
    )
    totals.update({
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "passed_cases": sum(1 for item in case_results if item["passed"]),
    })
    return {"summary": totals, "cases": case_results}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--fail-under-precision", type=float, default=0.90)
    parser.add_argument("--fail-under-recall", type=float, default=0.95)
    parser.add_argument("--json", action="store_true", help="Print machine-readable output")
    args = parser.parse_args()

    report = evaluate(args.fixture)
    summary = report["summary"]
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        for case in report["cases"]:
            if case["passed"]:
                continue
            print(f"FAIL {case['id']}")
            for field in ("missing", "wrong_type", "unexpected", "forbidden"):
                if case[field]:
                    print(f"  {field}: {', '.join(case[field])}")
        print(
            "Entity quality: "
            f"{summary['passed_cases']}/{summary['cases']} cases, "
            f"precision={summary['precision']:.1%}, "
            f"recall={summary['recall']:.1%}, "
            f"F1={summary['f1']:.1%}, "
            f"forbidden={summary['forbidden']}"
        )

    passed = (
        summary["precision"] >= args.fail_under_precision
        and summary["recall"] >= args.fail_under_recall
        and summary["forbidden"] == 0
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
