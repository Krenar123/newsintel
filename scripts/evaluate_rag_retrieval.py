"""Evaluate retrieval relevance, abstention, and scope leakage from a YAML set."""

from __future__ import annotations

import argparse
import datetime
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
from typing import Any

import yaml

from src.intelligence.retrieval import RetrievalDocument, rank_documents


def load_dataset(path: Path) -> tuple[list[RetrievalDocument], list[dict[str, Any]]]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    documents = []
    for row in payload.get("documents", []):
        published = row.get("published_at")
        documents.append(RetrievalDocument(
            document_id=int(row["id"]),
            title=str(row.get("title") or ""),
            content=str(row.get("content") or ""),
            summary=str(row.get("summary") or ""),
            entity_names=tuple(row.get("entities") or []),
            source_name=str(row.get("source_name") or "Unknown"),
            source_id=row.get("source_id"),
            published_at=datetime.datetime.fromisoformat(published) if published else None,
            reliability_score=row.get("reliability_score"),
            language=str(row.get("language") or ""),
        ))
    return documents, list(payload.get("queries") or [])


def evaluate_dataset(documents, queries, *, k=10):
    rows, reciprocal_ranks, recalls, precisions, ndcgs = [], [], [], [], []
    abstention_correct, forbidden_hits = [], []
    all_ids = [document.document_id for document in documents]
    for item in queries:
        allowed_ids = set(int(value) for value in item.get("allowed_document_ids", all_ids))
        permitted = [doc for doc in documents if doc.document_id in allowed_ids]
        relevant = set(int(value) for value in item.get("relevant_document_ids", []))
        forbidden = set(int(value) for value in item.get("forbidden_document_ids", []))
        outcome = rank_documents(str(item["query"]), permitted, limit=k)
        returned = [result.document.document_id for result in outcome.results]
        hits = [document_id for document_id in returned if document_id in relevant]
        recall = len(hits) / len(relevant) if relevant else float(outcome.abstained)
        precision = len(hits) / len(returned) if returned else float(not relevant)
        rank = next((i + 1 for i, value in enumerate(returned) if value in relevant), None)
        reciprocal_rank = 1 / rank if rank else 0.0
        dcg = sum((1.0 if value in relevant else 0.0) / math.log2(i + 2)
                  for i, value in enumerate(returned[:k]))
        ideal = sum(1.0 / math.log2(i + 2) for i in range(min(len(relevant), k)))
        ndcg = dcg / ideal if ideal else float(outcome.abstained)
        leaked = sorted(set(returned).intersection(forbidden))
        recalls.append(recall); precisions.append(precision)
        if relevant:
            reciprocal_ranks.append(reciprocal_rank)
        ndcgs.append(ndcg)
        abstention_correct.append(bool(outcome.abstained) == (not relevant))
        forbidden_hits.extend(leaked)
        rows.append({
            "id": item.get("id"), "query": item["query"], "returned_ids": returned,
            "relevant_ids": sorted(relevant), "recall_at_k": round(recall, 4),
            "precision_at_k": round(precision, 4),
            "reciprocal_rank": round(reciprocal_rank, 4),
            "ndcg_at_k": round(ndcg, 4), "abstained": outcome.abstained,
            "forbidden_hits": leaked,
        })
    metric = lambda values: round(sum(values) / max(1, len(values)), 4)
    report = {
        "query_count": len(queries), "document_count": len(documents),
        "source_count": len({doc.source_id or doc.source_name for doc in documents}), "k": k,
        "metrics": {
            "precision_at_k": metric(precisions), "recall_at_k": metric(recalls),
            "mrr": metric(reciprocal_ranks), "ndcg_at_k": metric(ndcgs),
            "abstention_accuracy": metric([float(v) for v in abstention_correct]),
            "forbidden_document_hits": len(forbidden_hits),
        },
        "queries": rows,
    }
    report["production_gate"] = production_gate(report)
    return report


def production_gate(report):
    metrics = report["metrics"]
    checks = {
        "minimum_50_queries": report["query_count"] >= 50,
        "minimum_10_sources": report["source_count"] >= 10,
        "precision_at_k_gte_0_90": metrics["precision_at_k"] >= 0.90,
        "recall_at_k_gte_0_95": metrics["recall_at_k"] >= 0.95,
        "mrr_gte_0_90": metrics["mrr"] >= 0.90,
        "ndcg_at_k_gte_0_90": metrics["ndcg_at_k"] >= 0.90,
        "perfect_abstention": metrics["abstention_accuracy"] == 1.0,
        "zero_forbidden_hits": metrics["forbidden_document_hits"] == 0,
    }
    return {"passed": all(checks.values()), "checks": checks}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--k", type=int, default=10)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--production", action="store_true")
    args = parser.parse_args()
    documents, queries = load_dataset(args.dataset)
    report = evaluate_dataset(documents, queries, k=args.k)
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    print(rendered)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    return 1 if args.production and not report["production_gate"]["passed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
