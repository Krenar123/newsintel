#!/usr/bin/env python3
"""Evaluate entity extraction on reviewer-labelled real article excerpts."""

import argparse
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.processing.entities import EntityExtractor


def _key(name: str, entity_type: str) -> tuple[str, str]:
    return EntityExtractor._canonicalize(name), entity_type


def _wilson_lower(successes: int, total: int, z: float = 1.96) -> float:
    if total == 0:
        return 0.0
    proportion = successes / total
    denominator = 1 + (z * z / total)
    centre = proportion + z * z / (2 * total)
    margin = z * math.sqrt((proportion * (1 - proportion) + z * z / (4 * total)) / total)
    return max(0.0, (centre - margin) / denominator)


def _metrics(tp: int, fp: int, fn: int) -> dict:
    precision = tp / (tp + fp) if tp + fp else 1.0
    recall = tp / (tp + fn) if tp + fn else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "true_positive": tp,
        "false_positive": fp,
        "false_negative": fn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "precision_wilson_95_lower": round(_wilson_lower(tp, tp + fp), 4),
        "recall_wilson_95_lower": round(_wilson_lower(tp, tp + fn), 4),
    }


def evaluate(paths: list[Path], split: str) -> dict:
    records = []
    seen_ids = set()
    for path in paths:
        with path.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                record = json.loads(line)
                if record.get("split") != split:
                    continue
                record_id = record.get("record_id")
                if not record_id or record_id in seen_ids:
                    raise ValueError(f"Duplicate or missing record_id at {path}:{line_number}")
                seen_ids.add(record_id)
                gold = (record.get("annotation") or {}).get("gold_entities")
                if gold is None:
                    continue
                records.append(record)

    extractor = EntityExtractor(languages=["mk", "sq", "en"])
    totals = {"tp": 0, "fp": 0, "fn": 0}
    publishable_totals = {"tp": 0, "fp": 0, "fn": 0}
    breakdown = defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0})
    failures = []
    sources = set()

    for record in records:
        result = extractor.extract(
            str(record.get("text", "")),
            language=str(record.get("language", "mk")),
            max_entities=200,
        )
        gold = {
            _key(str(item["name"]), str(item["type"]))
            for item in record["annotation"]["gold_entities"]
        }
        actual = {(item.canonical_name, item.entity_type) for item in result.entities}
        publishable = {
            (item.canonical_name, item.entity_type)
            for item in result.entities
            if item.publishable
        }
        true_positive = actual & gold
        false_positive = actual - gold
        false_negative = gold - actual
        pub_true_positive = publishable & gold
        pub_false_positive = publishable - gold
        pub_false_negative = gold - publishable

        totals["tp"] += len(true_positive)
        totals["fp"] += len(false_positive)
        totals["fn"] += len(false_negative)
        publishable_totals["tp"] += len(pub_true_positive)
        publishable_totals["fp"] += len(pub_false_positive)
        publishable_totals["fn"] += len(pub_false_negative)
        language = str(record.get("language") or "unknown")
        source = str(record.get("source") or "unknown")
        sources.add(source)
        for label in (f"language:{language}", f"source:{source}"):
            breakdown[label]["tp"] += len(true_positive)
            breakdown[label]["fp"] += len(false_positive)
            breakdown[label]["fn"] += len(false_negative)
        for entity_type in ("person", "organization", "location"):
            typed_gold = {item for item in gold if item[1] == entity_type}
            typed_actual = {item for item in actual if item[1] == entity_type}
            breakdown[f"type:{entity_type}"]["tp"] += len(typed_gold & typed_actual)
            breakdown[f"type:{entity_type}"]["fp"] += len(typed_actual - typed_gold)
            breakdown[f"type:{entity_type}"]["fn"] += len(typed_gold - typed_actual)

        if false_positive or false_negative or pub_false_positive:
            failures.append({
                "record_id": record["record_id"],
                "source": source,
                "false_positive": sorted(f"{name} [{kind}]" for name, kind in false_positive),
                "false_negative": sorted(f"{name} [{kind}]" for name, kind in false_negative),
                "publishable_false_positive": sorted(
                    f"{name} [{kind}]" for name, kind in pub_false_positive
                ),
            })

    return {
        "split": split,
        "records": len(records),
        "sources": len(sources),
        "overall": _metrics(totals["tp"], totals["fp"], totals["fn"]),
        "publishable": _metrics(
            publishable_totals["tp"],
            publishable_totals["fp"],
            publishable_totals["fn"],
        ),
        "breakdown": {
            label: _metrics(values["tp"], values["fp"], values["fn"])
            for label, values in sorted(breakdown.items())
        },
        "failures": failures[:100],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="+", type=Path)
    parser.add_argument("--split", choices=["calibration", "holdout"], default="holdout")
    parser.add_argument("--production", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    report = evaluate(args.inputs, args.split)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        overall = report["overall"]
        publishable = report["publishable"]
        print(
            f"Entity corpus {report['split']}: {report['records']} articles, "
            f"{report['sources']} sources, precision={overall['precision']:.1%}, "
            f"recall={overall['recall']:.1%}, publishable precision="
            f"{publishable['precision']:.1%}, publishable recall={publishable['recall']:.1%}"
        )
        for failure in report["failures"][:20]:
            print(f"  FAIL {failure['record_id']}: {failure}")

    if not args.production:
        passed = report["records"] > 0 and not report["failures"]
        report["production_gate"] = {"requested": False, "passed": passed}
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(
                json.dumps(report, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        return 0 if passed else 1

    # Production gates require both excellent point estimates and enough
    # independent real-world evidence for the lower confidence bound to matter.
    publishable = report["publishable"]
    overall = report["overall"]
    passed = (
        report["records"] >= 100
        and report["sources"] >= 10
        and publishable["precision"] >= 0.995
        and publishable["precision_wilson_95_lower"] >= 0.98
        and publishable["recall"] >= 0.97
        and overall["precision"] >= 0.95
        and overall["recall"] >= 0.95
    )
    report["production_gate"] = {
        "requested": True,
        "passed": passed,
        "minimum_records": 100,
        "minimum_sources": 10,
        "minimum_publishable_precision": 0.995,
        "minimum_publishable_precision_wilson_95_lower": 0.98,
        "minimum_publishable_recall": 0.97,
        "minimum_candidate_precision": 0.95,
        "minimum_candidate_recall": 0.95,
    }
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    if not passed and not args.json:
        print(
            "PRODUCTION GATE FAILED: need >=100 blinded holdout articles, >=10 sources, "
            ">=99.5% publishable precision (>=98% Wilson lower bound), >=97% "
            "publishable recall, and >=95% candidate precision/recall."
        )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
