# Production Retrieval and Grounded RAG

NewsIntel uses retrieval-augmented generation only after account permissions and
article quality filters have been applied. The language model never chooses the
client scope and cannot request documents belonging to another client.

## Request Path

1. Authenticate the user and authorize the requested client.
2. Enforce plan history and chat limits.
3. Build the client's permitted candidate set from its watchlist and persona.
4. Add wider country context only for admin, analyst, or explicitly entitled clients.
5. Rank candidates with the deterministic multilingual hybrid retriever.
6. Abstain when no candidate reaches the relevance threshold.
7. Build labeled source and legal evidence.
8. Optionally ask the configured AI provider to improve wording.
9. Reject generated output unless every factual sentence has permitted citations,
   every claim has an exact source quote, and claim wording overlaps its evidence.
10. Store the answer, citations, retrieval diagnostics, scope decision, and history.

## Retriever

`src/intelligence/retrieval.py` implements:

- Macedonian Cyrillic/Latin and Albanian-aware query forms
- cross-script stopword filtering
- BM25F-style title, summary, approved-entity, and article-content scoring
- exact phrase and approved entity boosts
- bounded freshness and source reliability refinements
- per-source caps and near-story diversity penalties
- a minimum relevance threshold and explicit abstention
- auditable per-document score components

Freshness and source reliability cannot admit a document without a lexical or
entity match. The retriever receives only documents already allowed by the
client's permission scope.

## Configuration

```dotenv
RAG_MINIMUM_SCORE=0.85
RAG_MAX_PER_SOURCE=4
RAG_MAX_EVIDENCE=16
```

These settings are deployment-validated. Do not lower the relevance threshold
to conceal retrieval misses; improve aliases, article text, or the evaluation
set instead.

## Evaluation

The compact multilingual regression fixture can be run with:

```powershell
.\venv\Scripts\python.exe scripts\evaluate_rag_retrieval.py tests\fixtures\rag_retrieval_mk.yaml
```

A production holdout report must contain at least 50 representative questions
from at least 10 sources and pass all gates:

- precision@10 >= 0.90
- recall@10 >= 0.95
- MRR >= 0.90
- nDCG@10 >= 0.90
- abstention accuracy = 1.00
- forbidden-document hits = 0

Run the final dataset with:

```powershell
.\venv\Scripts\python.exe scripts\evaluate_rag_retrieval.py <holdout.yaml> --production --output data\rag_evaluations\latest_quality_report.json
```

The environment validator reads that report in production. Human creation and
review of the final holdout remains an external certification gate; the engine,
metrics, fixtures, and release enforcement are already implemented.
