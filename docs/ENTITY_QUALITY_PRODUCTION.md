# Production Entity Quality

NewsIntel uses a precision-first entity architecture. Statistical models may
discover candidates, but they cannot publish a person, organization, or
location to a client by themselves.

## Trust Boundary

1. The country registry is loaded from `config/entities/north_macedonia.yaml`.
2. Startup validation rejects duplicate canonical records and aliases owned by
   more than one entity.
3. The matcher normalizes Unicode, tolerates punctuation and dash variants,
   respects word boundaries, prefers the longest alias, and treats short
   acronyms as case-sensitive.
4. A curated alias may publish automatically. A model-only discovery enters
   `NEEDS_REVIEW`.
5. Staff approval records reviewer identity, time, evidence, provenance, and a
   trust tier.
6. Client search, trends, dossiers, chat, and reports only use `APPROVED`
   entities.

Frequency, model confidence, or agreement between models never bypasses review.

## Local Model Ensemble

spaCy remains the baseline candidate model. GLiNER multilingual can be enabled
on the ingestion worker to improve discovery of Macedonian and Albanian names.

Install the optional stack:

```powershell
.\venv\Scripts\python.exe -m pip install -r requirements-ner.txt
```

Then set:

```env
ENABLE_GLINER_NER=true
GLINER_MODEL=urchade/gliner_multi-v2.1
GLINER_THRESHOLD=0.62
```

The first model load downloads the model. Cache it in the production image or
persistent model volume. Do not enable it in production until the blinded
holdout gate passes.

## Registry And Synthetic Regression

```powershell
.\venv\Scripts\python.exe scripts\validate_entity_registry.py
.\venv\Scripts\python.exe scripts\evaluate_entities.py
.\venv\Scripts\python.exe -m pytest tests\test_entity_quality.py tests\test_entity_registry.py -q
```

The compact fixture protects known aliases and adversarial cases. A perfect
score there is only a regression result; it is not evidence of real-world
production accuracy.

## Real-Article Corpus

Export a source-stratified batch without running ingestion:

```powershell
.\venv\Scripts\python.exe scripts\export_entity_annotation_batch.py --limit 1000
```

Each JSONL record contains an article excerpt and an empty
`annotation.gold_entities` value. A reviewer fills it with every person,
organization, and location in the excerpt:

```json
{
  "gold_entities": [
    {"name": "Христијан Мицкоски", "type": "person"},
    {"name": "Скопје", "type": "location"}
  ]
}
```

Use the calibration split to improve aliases and rules. Never tune against the
holdout split. Evaluate the blinded holdout:

```powershell
.\venv\Scripts\python.exe scripts\evaluate_entity_annotations.py data\entity_annotations\entity_batch_TIMESTAMP.jsonl --split holdout --production --output data\entity_annotations\latest_quality_report.json
```

The production gate requires at least 100 labelled holdout articles from at
least 10 sources, 99.5% client-publishable precision, a 98% lower Wilson
confidence bound, 97% publishable recall, and 95% candidate precision/recall.

## Promotion Rules

- Add stable, verified public figures, parties, institutions, and locations to
  the registry with Cyrillic, Latin, Albanian, and common inflected aliases.
- Use structured alias objects with `languages`, `requires_any`,
  `excludes_any`, `case_sensitive`, or `publishable: false` when a surface
  form is ambiguous.
- Approve a discovered entity only after checking at least one original source
  and its article context.
- Merge records only when identity is confirmed. The extractor deliberately
  does not merge substrings or shared surnames.
- Keep the original candidate and review metadata for auditability.

## Current Certification State

The implementation has production safety controls, but the system is not
certified at production accuracy until the owner-labelled real-article holdout
passes. This distinction prevents a small curated fixture from being presented
as near-100% real-world accuracy.
