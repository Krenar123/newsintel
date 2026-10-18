"""Deterministic, multilingual evidence retrieval for grounded intelligence."""

from __future__ import annotations

import datetime
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Iterable, Optional

from src.search.normalization import normalize_text, search_variants


_TOKEN_RE = re.compile(r"[\w\u0400-\u04ff]+", flags=re.UNICODE)
_STOPWORDS = {
    "a", "about", "and", "are", "for", "from", "how", "in", "is", "latest",
    "me", "of", "on", "please", "show", "tell", "that", "the", "this", "to",
    "what", "when", "where", "which", "who", "why", "with", "mention",
    "mentions", "coverage", "recent", "today",
    "за", "со", "од", "на", "во", "и", "или", "ова", "тоа", "овој", "кој",
    "која", "како", "каде", "кога", "зошто", "што", "ми", "кажи", "покажи",
    "dhe", "e", "i", "kjo", "ku", "kush", "me", "nga", "per", "për", "që",
    "si", "tek", "te", "çfarë",
}


def _expanded_stopwords() -> frozenset[str]:
    forms = set(_STOPWORDS)
    for word in _STOPWORDS:
        for variant in search_variants(word):
            forms.update(_TOKEN_RE.findall(variant))
    return frozenset(forms)


_STOPWORD_FORMS = _expanded_stopwords()


@dataclass(frozen=True)
class RetrievalDocument:
    """A permission-filtered document supplied to the ranker."""

    document_id: int
    title: str
    content: str = ""
    summary: str = ""
    entity_names: tuple[str, ...] = ()
    source_name: str = "Unknown"
    source_id: Optional[int] = None
    published_at: Optional[datetime.datetime] = None
    reliability_score: Optional[float] = None
    language: str = ""
    metadata: dict = field(default_factory=dict, compare=False)


@dataclass(frozen=True)
class RankedDocument:
    document: RetrievalDocument
    score: float
    lexical_score: float
    phrase_score: float
    entity_score: float
    freshness_score: float
    source_quality_score: float
    query_coverage: float
    matched_terms: tuple[str, ...]

    def diagnostics(self) -> dict:
        return {
            "document_id": self.document.document_id,
            "score": round(self.score, 4),
            "lexical_score": round(self.lexical_score, 4),
            "phrase_score": round(self.phrase_score, 4),
            "entity_score": round(self.entity_score, 4),
            "freshness_score": round(self.freshness_score, 4),
            "source_quality_score": round(self.source_quality_score, 4),
            "query_coverage": round(self.query_coverage, 4),
            "matched_terms": list(self.matched_terms),
        }


@dataclass(frozen=True)
class RetrievalOutcome:
    results: tuple[RankedDocument, ...]
    query_terms: tuple[str, ...]
    considered_count: int
    eligible_count: int
    source_count: int
    abstained: bool
    abstention_reason: str = ""

    def diagnostics(self) -> dict:
        return {
            "engine": "hybrid_bm25f_v1",
            "query_terms": list(self.query_terms),
            "considered_count": self.considered_count,
            "eligible_count": self.eligible_count,
            "returned_count": len(self.results),
            "source_count": self.source_count,
            "abstained": self.abstained,
            "abstention_reason": self.abstention_reason,
            "top_results": [item.diagnostics() for item in self.results[:5]],
        }


def query_terms(value: str) -> tuple[str, ...]:
    """Return distinct Cyrillic/Latin-aware content terms for retrieval."""
    terms: list[str] = []
    seen: set[str] = set()
    for variant in search_variants(value):
        for token in _TOKEN_RE.findall(variant):
            if len(token) < 2 or token in _STOPWORD_FORMS or token in seen:
                continue
            seen.add(token)
            terms.append(token)
    return tuple(terms[:32])


def rank_documents(
    query: str,
    documents: Iterable[RetrievalDocument],
    *,
    limit: int = 12,
    minimum_score: float = 0.85,
    max_per_source: int = 4,
    now: Optional[datetime.datetime] = None,
) -> RetrievalOutcome:
    """Rank authorized documents and abstain when the evidence is weak.

    BM25F-style lexical evidence is the dominant signal. Exact phrases, known
    entity names, publication freshness, and configured source reliability only
    refine documents that already have a lexical match.
    """
    docs = list(documents)
    terms = query_terms(query)
    if not terms:
        return RetrievalOutcome(
            results=(), query_terms=(), considered_count=len(docs), eligible_count=0,
            source_count=0, abstained=True,
            abstention_reason="The question did not contain enough searchable terms.",
        )
    if not docs:
        return RetrievalOutcome(
            results=(), query_terms=terms, considered_count=0, eligible_count=0,
            source_count=0, abstained=True,
            abstention_reason="No documents were available inside the permitted scope.",
        )

    prepared = [_prepare_document(document) for document in docs]
    document_frequency = Counter()
    for item in prepared:
        present = set()
        for field_tokens in item["tokens"].values():
            present.update(field_tokens)
        for term in terms:
            if term in present:
                document_frequency[term] += 1

    current_time = now or datetime.datetime.utcnow()
    scored: list[RankedDocument] = []
    total_documents = len(prepared)
    for item in prepared:
        document = item["document"]
        field_tokens = item["tokens"]
        matched_terms = tuple(
            term for term in terms
            if any(term in tokens for tokens in field_tokens.values())
        )
        if not matched_terms:
            continue

        lexical = 0.0
        field_weights = {"title": 4.0, "summary": 2.2, "entities": 3.4, "content": 1.0}
        field_b = {"title": 0.25, "summary": 0.55, "entities": 0.2, "content": 0.8}
        averages = item["averages"]
        for term in matched_terms:
            df = document_frequency[term]
            inverse_document_frequency = math.log(
                1 + ((total_documents - df + 0.5) / (df + 0.5))
            )
            for field_name, tokens in field_tokens.items():
                frequency = tokens.count(term)
                if not frequency:
                    continue
                length_norm = 1 - field_b[field_name] + field_b[field_name] * (
                    len(tokens) / max(1.0, averages[field_name])
                )
                lexical += field_weights[field_name] * inverse_document_frequency * (
                    (frequency * 2.2) / (frequency + 1.2 * length_norm)
                )

        coverage = len(matched_terms) / max(1, len(terms))
        normalized_queries = [normalize_text(variant) for variant in search_variants(query)]
        phrase = 0.0
        if len(terms) >= 2:
            if any(value and value in item["normalized"]["title"] for value in normalized_queries):
                phrase = 3.0
            elif any(value and value in item["normalized"]["body"] for value in normalized_queries):
                phrase = 1.5

        entity = 0.0
        query_forms = set(normalized_queries)
        for entity_name in document.entity_names:
            entity_forms = set(search_variants(entity_name))
            if query_forms.intersection(entity_forms):
                entity = max(entity, 3.0)
            elif set(query_terms(entity_name)).intersection(matched_terms):
                entity = max(entity, 1.0)

        freshness = _freshness_score(document.published_at, current_time)
        reliability = _source_quality_score(document.reliability_score)
        score = lexical + phrase + entity + freshness + reliability + (coverage * 1.5)
        if score < minimum_score:
            continue
        scored.append(RankedDocument(
            document=document,
            score=score,
            lexical_score=lexical,
            phrase_score=phrase,
            entity_score=entity,
            freshness_score=freshness,
            source_quality_score=reliability,
            query_coverage=coverage,
            matched_terms=matched_terms,
        ))

    scored.sort(key=lambda item: (
        item.score,
        item.document.published_at or datetime.datetime.min,
        -item.document.document_id,
    ), reverse=True)

    selected: list[RankedDocument] = []
    source_usage: defaultdict[str, int] = defaultdict(int)
    remaining = list(scored)
    while remaining and len(selected) < limit:
        best_index = -1
        best_adjusted = -1.0
        for index, candidate in enumerate(remaining):
            source_key = str(candidate.document.source_id or candidate.document.source_name)
            if source_usage[source_key] >= max_per_source:
                continue
            repeat_penalty = 1.0 / (1.0 + 0.22 * source_usage[source_key])
            duplicate_penalty = _story_similarity_penalty(candidate, selected)
            adjusted = candidate.score * repeat_penalty * duplicate_penalty
            if adjusted > best_adjusted:
                best_adjusted = adjusted
                best_index = index
        if best_index < 0:
            break
        chosen = remaining.pop(best_index)
        selected.append(chosen)
        source_usage[str(chosen.document.source_id or chosen.document.source_name)] += 1

    source_count = len({
        item.document.source_id or item.document.source_name for item in selected
    })
    abstained = not selected
    return RetrievalOutcome(
        results=tuple(selected), query_terms=terms, considered_count=len(docs),
        eligible_count=len(scored), source_count=source_count, abstained=abstained,
        abstention_reason=(
            "No permitted document met the minimum relevance threshold."
            if abstained else ""
        ),
    )


def _prepare_document(document: RetrievalDocument) -> dict:
    normalized = {
        "title": " ".join(search_variants(document.title)),
        "summary": " ".join(search_variants(document.summary)),
        "entities": " ".join(
            variant for name in document.entity_names for variant in search_variants(name)
        ),
        "content": " ".join(search_variants(document.content)),
    }
    tokens = {
        name: _TOKEN_RE.findall(value)
        for name, value in normalized.items()
    }
    return {
        "document": document,
        "normalized": {
            "title": normalize_text(document.title),
            "body": normalize_text(f"{document.summary} {document.content}"),
        },
        "tokens": tokens,
        "averages": {
            "title": 12.0,
            "summary": 60.0,
            "entities": 12.0,
            "content": 500.0,
        },
    }


def _freshness_score(
    published_at: Optional[datetime.datetime],
    now: datetime.datetime,
) -> float:
    if not published_at:
        return 0.0
    reference = now
    observed = published_at
    if observed.tzinfo is not None and reference.tzinfo is None:
        reference = reference.replace(tzinfo=datetime.timezone.utc)
    elif observed.tzinfo is None and reference.tzinfo is not None:
        observed = observed.replace(tzinfo=datetime.timezone.utc)
    age_days = max(0.0, (reference - observed).total_seconds() / 86400)
    return 0.55 * math.exp(-age_days / 120.0)


def _source_quality_score(reliability_score: Optional[float]) -> float:
    if reliability_score is None:
        return 0.0
    bounded = min(1.0, max(0.0, float(reliability_score)))
    return 0.4 * bounded


def _story_similarity_penalty(
    candidate: RankedDocument,
    selected: list[RankedDocument],
) -> float:
    candidate_terms = set(query_terms(candidate.document.title))
    if not candidate_terms:
        return 1.0
    for item in selected:
        existing_terms = set(query_terms(item.document.title))
        union = candidate_terms.union(existing_terms)
        if union and len(candidate_terms.intersection(existing_terms)) / len(union) >= 0.82:
            return 0.72
    return 1.0
