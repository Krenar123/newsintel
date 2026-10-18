"""Database-aware full-text predicates used by search and client intelligence."""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import func, literal_column, or_

from src.models.database import Article, Entity, EntityStatus
from src.search.normalization import search_variants


_SIMPLE_CONFIG = literal_column("'simple'::regconfig")


def client_publishable_entity_filter():
    """SQL predicate for entities approved for client-facing surfaces."""
    return Entity.status == EntityStatus.APPROVED


def is_client_publishable_entity(entity: Entity | None) -> bool:
    """In-memory equivalent of client_publishable_entity_filter."""
    return bool(entity and entity.status == EntityStatus.APPROVED)


def article_text_match(session, terms: Iterable[str], *, exact: bool = False):
    """Build a PostgreSQL FTS predicate with a portable development fallback."""
    values = _expanded_terms(terms, exact=exact)
    if not values:
        return None

    if _dialect_name(session) == "postgresql":
        vector = func.to_tsvector(
            _SIMPLE_CONFIG,
            func.coalesce(Article.search_text, ""),
        )
        conditions = [
            vector.op("@@")(func.websearch_to_tsquery(_SIMPLE_CONFIG, value))
            for value in values
        ]
        return or_(*conditions)

    return or_(*[
        Article.search_text.ilike(f"%{value}%")
        for value in values
    ])


def entity_text_match(session, terms: Iterable[str], *, exact: bool = False):
    """Build an entity-name predicate using the same database strategy."""
    values = _expanded_terms(terms, exact=exact)
    if not values:
        return None

    if _dialect_name(session) == "postgresql":
        vector = func.to_tsvector(
            _SIMPLE_CONFIG,
            func.coalesce(Entity.search_text, ""),
        )
        conditions = [
            vector.op("@@")(func.websearch_to_tsquery(_SIMPLE_CONFIG, value))
            for value in values
        ]
        return or_(*conditions)

    conditions = []
    for value in values:
        pattern = f"%{value}%"
        conditions.extend([
            Entity.search_text.ilike(pattern),
            Entity.canonical_name.ilike(pattern),
            Entity.name.ilike(pattern),
        ])
    return or_(*conditions)


def _expanded_terms(terms: Iterable[str], *, exact: bool) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for term in terms:
        cleaned = str(term or "").strip()
        if not cleaned:
            continue
        candidates = [cleaned] if exact else search_variants(cleaned)
        for candidate in candidates:
            value = candidate.strip()
            key = value.casefold()
            if value and key not in seen:
                seen.add(key)
                values.append(value)
    return values[:24]


def _dialect_name(session) -> str:
    bind = session.get_bind()
    return bind.dialect.name if bind is not None else ""
