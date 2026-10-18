# NewsIntel Quality Scorecard

This scorecard defines the measurable release gates for a 9/10 intelligence
product. A feature is not considered production-ready because it exists; it is
ready only when its gate is measured on representative Macedonian and Albanian
data and remains green in regression testing.

## Release Gates

| Area | 9/10 gate | Measurement |
| --- | --- | --- |
| Entity publication | >= 99% precision and >= 90% recall for tracked entities | Versioned, human-labelled MK/SQ fixture set |
| Entity discovery | >= 98% precision before review | Entity evaluator |
| Entity trust | 100% of client-visible entities are APPROVED | API/query regression tests |
| Alias resolution | >= 98% of tested Cyrillic, Latin, Albanian and inflected aliases resolve to one canonical entity | Alias fixture suite |
| Duplicate control | < 2% duplicate leakage in a weekly reviewed sample | Ingestion quality report |
| Article dates | >= 99% valid publication dates; retrieval time always present | Date extraction audit |
| Attack extraction | >= 90% precision, >= 80% recall, with original speaker separated from reporting source | Labelled attack evaluation set |
| Search retrieval | >= 90% nDCG@10 on a multilingual query set | Search/RAG evaluation |
| Grounded AI | 100% factual claims have valid evidence citations; unsupported questions abstain | Adversarial grounded-answer suite |
| Client isolation | Zero cross-client leakage | Permission and browser E2E tests |
| Freshness | 95% of healthy sources ingested within 15 minutes | Scheduler/source monitoring |
| Availability | >= 99.5% monthly API availability during pilot | External uptime monitoring |
| Performance | p95 dashboard API response < 2.5 seconds | Production telemetry |
| Recovery | Daily backup; restore drill succeeds quarterly | Signed operations record |

## Entity Publication Policy

- APPROVED: may appear in client article badges, entity search, trends,
  related entities, dossiers, chat context and reports.
- AUTO: legacy/unreviewed and never client-publishable.
- NEEDS_REVIEW: stored for administrator review and never client-publishable.
- HIDDEN: confirmed noise, duplicate alias record or retired record.
- Article full-text search is independent of entity publication status, so an
  unknown name remains discoverable without being represented as a trusted
  structured entity.

Curated lexicon matches have confidence 1.0, provenance curated_lexicon, and
are approved. spaCy model discoveries use a conservative non-calibrated
confidence, provenance spacy_ner, and enter NEEDS_REVIEW.

## Evaluation Commands

Run:

    .\venv\Scripts\python.exe scripts\evaluate_entities.py
    .\venv\Scripts\python.exe -m pytest tests\test_entity_quality.py -q
    .\venv\Scripts\python.exe scripts\sync_entity_lexicon.py --country mk --transition-auto

The final command is a dry run. Apply only after reviewing its counts:

    .\venv\Scripts\python.exe scripts\sync_entity_lexicon.py --country mk --transition-auto --batch-size 5000 --apply

Unknown entities should later receive a promotion report based on distinct
articles, distinct sources, recency and reviewer decisions. Frequency alone
must never auto-approve an entity.
