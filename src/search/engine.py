"""
Search Engine — Full-text article search and entity lookup.

Supports:
  - Full-text search across article titles and content
  - Entity search (find all articles about a person/org)
  - Category filtering
  - Date range filtering
  - Source filtering
  - Trending entities detection
"""

import datetime
from typing import Optional
from dataclasses import dataclass

from sqlalchemy.orm import Session
from sqlalchemy import func, desc, and_, or_, select

from src.models.database import (
    Article, Summary, Entity, EntityMention, ArticleCategory, Source,
    SummaryType, EntityType, EntityStatus,
)
from src.processing.entities import corrected_entity_type, is_likely_entity_name
from src.search.normalization import search_variants
from src.search.predicates import article_text_match, entity_text_match

import structlog

logger = structlog.get_logger()


@dataclass
class SearchFilters:
    """Search filter parameters."""
    query: Optional[str] = None
    category: Optional[str] = None
    source_id: Optional[int] = None
    country_code: Optional[str] = None
    language: Optional[str] = None
    date_from: Optional[datetime.datetime] = None
    date_to: Optional[datetime.datetime] = None
    date_basis: str = "published"
    entity_id: Optional[int] = None
    entity_name: Optional[str] = None
    exact_phrase: bool = False
    source_type: Optional[str] = None
    min_reliability: Optional[float] = None
    sentiment: Optional[str] = None
    limit: int = 20
    offset: int = 0


class SearchEngine:
    """Searches articles, entities, and trends."""

    def __init__(self, session: Session):
        self.session = session

    # ------------------------------------------------------------------
    # Article search
    # ------------------------------------------------------------------

    def search_articles(self, filters: SearchFilters) -> dict:
        """
        Search articles with full-text query and filters.

        Returns dict with articles list and pagination info.
        """
        query = self.session.query(Article).filter(
            or_(
                Article.quality_status == None,
                Article.quality_status != "excluded",
            )
        )
        if filters.category:
            query = query.join(ArticleCategory)
        if (
            filters.source_type
            or filters.min_reliability is not None
            or filters.country_code
        ):
            query = query.join(Source)

        # Text matching uses PostgreSQL FTS and the local SQLite fallback.
        if filters.query:
            condition = article_text_match(
                self.session,
                [filters.query],
                exact=filters.exact_phrase,
            )
            if condition is not None:
                query = query.filter(condition)

        # Category filter
        if filters.category:
            query = query.filter(ArticleCategory.category == filters.category)

        # Source filter
        if filters.source_id:
            query = query.filter(Article.source_id == filters.source_id)

        if filters.source_type:
            query = query.filter(Source.source_type == filters.source_type)

        if filters.min_reliability is not None:
            query = query.filter(Source.reliability_score >= filters.min_reliability)

        # Country filter
        if filters.country_code:
            query = query.filter(Source.country_code == filters.country_code)

        # Language filter
        if filters.language:
            query = query.filter(Article.language == filters.language)

        # Date range. published = outlet date, fetched = collection date,
        # ingested = database insert date.
        date_columns = {
            "published": Article.published_at,
            "fetched": Article.fetched_at,
            "ingested": Article.ingested_at,
        }
        date_column = date_columns.get(filters.date_basis, Article.published_at)
        if filters.date_from:
            query = query.filter(date_column >= filters.date_from)
        if filters.date_to:
            query = query.filter(date_column <= filters.date_to)

        # Entity filter
        if filters.entity_id:
            query = query.join(EntityMention).filter(
                EntityMention.entity_id == filters.entity_id
            )

        if filters.sentiment:
            sentiment_query = select(EntityMention.article_id)
            if filters.sentiment == "positive":
                sentiment_query = sentiment_query.where(EntityMention.sentiment_score >= 0.05)
            elif filters.sentiment == "negative":
                sentiment_query = sentiment_query.where(EntityMention.sentiment_score <= -0.05)
            elif filters.sentiment == "neutral":
                sentiment_query = sentiment_query.where(
                    EntityMention.sentiment_score > -0.05,
                    EntityMention.sentiment_score < 0.05,
                )
            if filters.sentiment in {"positive", "negative", "neutral"}:
                query = query.filter(Article.id.in_(sentiment_query))

        # Count total before pagination
        total = (
            query.with_entities(func.count(func.distinct(Article.id)))
            .scalar()
            or 0
        )

        # Fetch results
        articles = (
            query.distinct()
            .order_by(desc(Article.published_at))
            .offset(filters.offset)
            .limit(filters.limit)
            .all()
        )

        return {
            "articles": articles,
            "total": total,
            "limit": filters.limit,
            "offset": filters.offset,
            "has_more": (filters.offset + filters.limit) < total,
        }

    # ------------------------------------------------------------------
    # Entity search
    # ------------------------------------------------------------------

    def search_entities(
        self,
        query: str,
        entity_type: Optional[EntityType] = None,
        limit: int = 20,
    ) -> list[Entity]:
        """Search entities by name."""
        q = self.session.query(Entity)
        q = q.filter(Entity.status != EntityStatus.HIDDEN)

        condition = entity_text_match(self.session, [query])
        if condition is not None:
            q = q.filter(condition)

        if entity_type:
            q = q.filter(Entity.entity_type == entity_type)

        candidates = (
            q.order_by(desc(Entity.total_mentions))
            .limit(limit * 5)
            .all()
        )
        return [
            entity for entity in candidates
            if is_likely_entity_name(entity.name, entity.entity_type.value)
        ][:limit]

    def get_entity_articles(
        self,
        entity_id: int,
        limit: int = 50,
        offset: int = 0,
    ) -> dict:
        """Get all articles mentioning a specific entity."""
        entity = self.session.query(Entity).get(entity_id)
        if not entity:
            return {"entity": None, "articles": [], "total": 0}

        query = (
            self.session.query(Article, EntityMention)
            .join(EntityMention)
            .join(Entity, Entity.id == EntityMention.entity_id)
            .filter(EntityMention.entity_id == entity_id)
            .filter(or_(Article.quality_status == None, Article.quality_status != "excluded"))
            .filter(Entity.status != EntityStatus.HIDDEN)
            .order_by(desc(Article.published_at))
        )

        total = query.count()
        results = query.offset(offset).limit(limit).all()

        return {
            "entity": entity,
            "articles": [
                {
                    "article": article,
                    "mention_count": mention.mention_count,
                    "context": mention.context_snippet,
                    "sentiment": mention.sentiment_score,
                }
                for article, mention in results
            ],
            "total": total,
            "has_more": (offset + limit) < total,
        }

    # ------------------------------------------------------------------
    # Trending entities
    # ------------------------------------------------------------------

    def get_trending_entities(
        self,
        days: int = 7,
        entity_type: Optional[EntityType] = None,
        limit: int = 20,
        country_code: Optional[str] = None,
    ) -> list[dict]:
        """
        Find entities trending in recent articles.

        Compares mention frequency in the last N days vs. the
        preceding N days to find entities with rising coverage.
        """
        now = datetime.datetime.utcnow()
        recent_start = now - datetime.timedelta(days=days)
        previous_start = recent_start - datetime.timedelta(days=days)

        # Recent mentions
        recent_q = (
            self.session.query(
                Entity.id,
                Entity.name,
                Entity.entity_type,
                func.sum(EntityMention.mention_count).label("recent_count"),
                func.count(func.distinct(Article.id)).label("recent_articles"),
            )
            .join(EntityMention, EntityMention.entity_id == Entity.id)
            .join(Article, Article.id == EntityMention.article_id)
            .filter(Article.published_at >= recent_start)
            .filter(or_(Article.quality_status == None, Article.quality_status != "excluded"))
            .filter(Entity.status != EntityStatus.HIDDEN)
        )

        if entity_type:
            recent_q = recent_q.filter(Entity.entity_type == entity_type)
        if country_code:
            recent_q = recent_q.join(Source, Source.id == Article.source_id).filter(
                Source.country_code == country_code
            )

        # Rank a bounded set of meaningful recent candidates before comparing
        # periods. This avoids SQLite's bind-variable limit and prevents both
        # SQLite and PostgreSQL from comparing tens of thousands of low-signal
        # entities that can never appear in the requested top results.
        recent_q = (
            recent_q
            .group_by(Entity.id, Entity.name, Entity.entity_type)
            .order_by(desc("recent_count"))
            .limit(max(limit * 30, 200))
        )
        recent_results = {r[0]: r for r in recent_q.all()}

        # Previous period mentions (for comparison)
        prev_q = (
            self.session.query(
                Entity.id,
                func.sum(EntityMention.mention_count).label("prev_count"),
            )
            .join(EntityMention, EntityMention.entity_id == Entity.id)
            .join(Article, Article.id == EntityMention.article_id)
            .filter(
                Article.published_at >= previous_start,
                Article.published_at < recent_start,
                or_(Article.quality_status == None, Article.quality_status != "excluded"),
            )
            .filter(Entity.id.in_(list(recent_results.keys())))
            .group_by(Entity.id)
        )
        prev_counts = {r[0]: r[1] for r in prev_q.all()}

        # Calculate trend scores
        trending = []
        for entity_id, recent in recent_results.items():
            if not is_likely_entity_name(recent[1], recent[2].value):
                continue
            prev_count = prev_counts.get(entity_id, 0) or 1
            recent_count = recent[3]  # recent_count
            trend_score = (recent_count - prev_count) / prev_count

            trending.append({
                "entity_id": entity_id,
                "name": recent[1],
                "entity_type": corrected_entity_type(recent[1], recent[2].value),
                "recent_mentions": recent_count,
                "recent_articles": recent[4],
                "previous_mentions": prev_counts.get(entity_id, 0),
                "trend_score": round(trend_score, 2),
                "trend_direction": (
                    "rising" if trend_score > 0.2
                    else "falling" if trend_score < -0.2
                    else "stable"
                ),
            })

        # Sort by trend score
        trending.sort(key=lambda x: x["trend_score"], reverse=True)
        return trending[:limit]

    # ------------------------------------------------------------------
    # Category stats
    # ------------------------------------------------------------------

    def get_category_stats(
        self,
        days: int = 7,
        country_code: Optional[str] = None,
    ) -> list[dict]:
        """Get article counts per category for the given period."""
        since = datetime.datetime.utcnow() - datetime.timedelta(days=days)

        query = (
            self.session.query(
                ArticleCategory.category,
                func.count(func.distinct(Article.id)).label("count"),
            )
            .join(Article)
            .filter(
                Article.published_at >= since,
                ArticleCategory.is_primary == True,
                or_(Article.quality_status == None, Article.quality_status != "excluded"),
            )
        )

        if country_code:
            query = query.join(Source).filter(
                Source.country_code == country_code
            )

        results = (
            query.group_by(ArticleCategory.category)
            .order_by(desc("count"))
            .all()
        )

        return [
            {"category": r[0], "article_count": r[1]}
            for r in results
        ]
