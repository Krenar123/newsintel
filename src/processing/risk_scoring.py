"""Political risk scoring from article, entity, source, and story signals."""

import datetime
from dataclasses import dataclass
from urllib.parse import urlparse

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from src.models.database import (
    Article,
    Client,
    ClientWatchlistItem,
    ClientType,
    Entity,
    EntityMention,
    Source,
    StoryCluster,
    StoryClusterArticle,
    WatchlistItemType,
)


ATTACK_TERMS = {
    "corruption": [
        "corruption", "bribe", "tender", "abuse of office",
        "корупција", "поткуп", "тендер", "злоупотреба",
    ],
    "crime_legal": [
        "criminal", "crime", "investigation", "arrest", "trial",
        "криминал", "истрага", "апсење", "судење", "обвин",
    ],
    "competence": [
        "incompetent", "failure", "resign", "scandal",
        "неспособ", "неуспех", "оставка", "скандал", "афера",
    ],
    "personal_attack": [
        "liar", "traitor", "shame", "hypocrite",
        "лажго", "предавник", "срам", "лицемер",
    ],
}

NARRATIVE_TERMS = {
    "eu_integration": ["еу", "европска унија", "брисел", "интеграција", "пристапување"],
    "elections": ["избори", "кампања", "анкета", "кандидат", "коалиција"],
    "corruption": ["корупција", "тендер", "набавка", "поткуп", "злоупотреба"],
    "security": ["криминал", "полиција", "безбедност", "насилство", "апсење"],
    "foreign_policy": ["бугарија", "грција", "србија", "косово", "нато", "регион"],
}

POLITICAL_CONTEXT_TERMS = [
    "government", "minister", "parliament", "party", "election", "campaign",
    "protest", "court", "prosecutor", "corruption", "eu", "nato",
    "влада", "министер", "собрание", "партија", "избор", "кампања",
    "протест", "суд", "обвинител", "корупција", "еу", "нато",
    "вмро", "сдсм", "дуи", "левица", "знам", "вреди",
]


@dataclass
class RiskResult:
    score: int
    level: str
    drivers: list[str]
    breakdown: dict
    metrics: dict
    items: list[dict]
    events: list[dict]
    alert_suggestions: list[dict]


class PoliticalRiskScorer:
    """Score country and client political/media risk using local DB signals."""

    def __init__(self, session: Session):
        self.session = session

    def country_risk(
        self,
        country_code: str = "mk",
        days: int = 7,
    ) -> RiskResult:
        since = datetime.datetime.utcnow() - datetime.timedelta(days=days)
        articles = (
            self.session.query(Article)
            .join(Source, Source.id == Article.source_id)
            .filter(Source.country_code == country_code)
            .filter(self._active_article_filter())
            .filter(self._article_date() >= since)
            .order_by(self._article_date().desc())
            .limit(500)
            .all()
        )
        clusters = (
            self.session.query(StoryCluster)
            .filter(StoryCluster.country_code == country_code)
            .filter(
                (StoryCluster.last_published_at >= since)
                | (StoryCluster.last_published_at == None)
            )
            .all()
        )
        return self._score_articles(articles, clusters, days)

    def client_risk(self, client_id: int, days: int = 30) -> RiskResult:
        client = self.session.query(Client).get(client_id)
        if not client:
            return RiskResult(0, "none", ["Client not found."], {}, {}, [], [], [])

        since = datetime.datetime.utcnow() - datetime.timedelta(days=days)
        watchlist = (
            self.session.query(ClientWatchlistItem)
            .filter(ClientWatchlistItem.client_id == client_id)
            .all()
        )
        article_ids: set[int] = set()
        for item in watchlist:
            article_ids.update(self._article_ids_for_watchlist_item(item, since))

        if not article_ids:
            return RiskResult(
                0,
                "none",
                ["No recent watchlist matches."],
                self._empty_breakdown(),
                {"watchlist_items": len(watchlist), "article_count": 0},
                [],
                [],
                [],
            )

        articles = (
            self.session.query(Article)
            .filter(Article.id.in_(article_ids))
            .filter(self._active_article_filter())
            .order_by(self._article_date().desc())
            .limit(500)
            .all()
        )
        clusters = self._clusters_for_articles({article.id for article in articles})
        return self._score_articles(articles, clusters, days, client=client, watchlist=watchlist)

    def _score_articles(
        self,
        articles: list[Article],
        clusters: list[StoryCluster],
        days: int,
        client: Client | None = None,
        watchlist: list[ClientWatchlistItem] | None = None,
    ) -> RiskResult:
        articles = [article for article in articles if self._is_content_article(article)]
        if not articles:
            return RiskResult(
                0,
                "none",
                ["No risk-relevant news articles in this period."],
                self._empty_breakdown(),
                {"article_count": 0},
                [],
                [],
                [],
            )
        sources = {article.source_id for article in articles}
        high_reliability_sources = {
            article.source_id
            for article in articles
            if article.source and (article.source.reliability_score or 0) >= 0.75
        }
        attack_hits: dict[str, int] = {}
        narrative_hits: dict[str, int] = {}
        negative_mentions = 0
        total_sentiment_mentions = 0
        high_reliability_attack_articles = 0
        political_articles = 0
        watchlist_articles = 0
        items = []

        for article in articles:
            text = f"{article.title} {article.content or ''}".lower()
            attacks = self._category_hits(text, ATTACK_TERMS)
            narratives = self._category_hits(text, NARRATIVE_TERMS)
            has_political_context = self._has_political_context(text, article)
            if has_political_context:
                political_articles += 1
            if watchlist and self._matches_watchlist_text(text, watchlist):
                watchlist_articles += 1
            for attack in attacks:
                attack_hits[attack] = attack_hits.get(attack, 0) + 1
            for narrative in narratives:
                narrative_hits[narrative] = narrative_hits.get(narrative, 0) + 1
            if attacks and has_political_context and article.source and (article.source.reliability_score or 0) >= 0.75:
                high_reliability_attack_articles += 1

            sentiments = [
                mention.sentiment_score
                for mention in article.entity_mentions
                if mention.sentiment_score is not None
            ]
            if sentiments:
                total_sentiment_mentions += len(sentiments)
                negative_mentions += sum(1 for value in sentiments if value < -0.05)

            if attacks or narratives or has_political_context:
                items.append({
                    "article_id": article.id,
                    "title": article.title,
                    "url": article.url,
                    "source_name": article.source.name if article.source else "Unknown",
                    "published_at": article.published_at,
                    "attack_categories": attacks,
                    "narratives": narratives,
                    "political_context": has_political_context,
                    "reliability": article.source.reliability_score if article.source else None,
                })

        validated_clusters = [cluster for cluster in clusters if cluster.status == "validated"]
        multi_source_clusters = [cluster for cluster in clusters if cluster.source_count >= 2]
        negative_ratio = (
            negative_mentions / total_sentiment_mentions
            if total_sentiment_mentions else 0
        )

        persona = client.client_type if client else None
        persona_weights = self._persona_weights(persona)
        volume_component = min(10, int((political_articles / max(1, days)) * 1.6))
        attack_component = min(20, sum(attack_hits.values())) if political_articles else 0
        sentiment_component = min(15, int(negative_ratio * 30))
        validation_component = min(12, len(validated_clusters) * 2 + len(multi_source_clusters))
        reliability_component = min(8, high_reliability_attack_articles)
        source_component = min(8, max(0, len(sources) - 2))
        watchlist_component = min(20, watchlist_articles * 3) if client else 0

        breakdown = {
            "political_volume": round(volume_component * persona_weights["volume"]),
            "attack_language": round(attack_component * persona_weights["attack"]),
            "negative_sentiment": round(sentiment_component * persona_weights["sentiment"]),
            "cross_source_validation": round(validation_component * persona_weights["validation"]),
            "high_reliability_sources": round(reliability_component * persona_weights["reliability"]),
            "source_spread": round(source_component * persona_weights["spread"]),
            "watchlist_relevance": round(watchlist_component * persona_weights["watchlist"]),
        }
        score = sum(breakdown.values())
        score = min(100, score)

        drivers = self._drivers(
            article_count=len(articles),
            source_count=len(sources),
            political_articles=political_articles,
            watchlist_articles=watchlist_articles,
            attack_hits=attack_hits,
            narrative_hits=narrative_hits,
            negative_ratio=negative_ratio,
            validated_clusters=len(validated_clusters),
            multi_source_clusters=len(multi_source_clusters),
            high_reliability_sources=len(high_reliability_sources),
        )
        metrics = {
            "article_count": len(articles),
            "political_article_count": political_articles,
            "watchlist_article_count": watchlist_articles,
            "source_count": len(sources),
            "high_reliability_source_count": len(high_reliability_sources),
            "attack_hits": attack_hits,
            "narrative_hits": narrative_hits,
            "negative_sentiment_ratio": round(negative_ratio, 2),
            "validated_cluster_count": len(validated_clusters),
            "multi_source_cluster_count": len(multi_source_clusters),
            "high_reliability_attack_articles": high_reliability_attack_articles,
        }
        return RiskResult(
            score=score,
            level=self._level(score),
            drivers=drivers,
            breakdown=breakdown,
            metrics=metrics,
            items=items[:12],
            events=self._risk_events(clusters, items, attack_hits),
            alert_suggestions=self._alert_suggestions(score, clusters, attack_hits, client),
        )

    def _clusters_for_articles(self, article_ids: set[int]) -> list[StoryCluster]:
        if not article_ids:
            return []
        return (
            self.session.query(StoryCluster)
            .join(StoryClusterArticle, StoryClusterArticle.cluster_id == StoryCluster.id)
            .filter(StoryClusterArticle.article_id.in_(article_ids))
            .distinct()
            .all()
        )

    def _article_ids_for_watchlist_item(
        self,
        item: ClientWatchlistItem,
        since: datetime.datetime,
    ) -> set[int]:
        if item.item_type in (WatchlistItemType.ENTITY, WatchlistItemType.OPPONENT) and item.entity_id:
            rows = (
                self.session.query(EntityMention.article_id)
                .join(Article, Article.id == EntityMention.article_id)
                .filter(EntityMention.entity_id == item.entity_id)
                .filter(self._active_article_filter())
                .filter(self._article_date() >= since)
                .all()
            )
            return {row[0] for row in rows}

        if item.item_type in (WatchlistItemType.KEYWORD, WatchlistItemType.TOPIC, WatchlistItemType.OPPONENT):
            value = (item.value or item.label or "").strip()
            if not value:
                return set()
            pattern = f"%{value}%"
            rows = (
                self.session.query(Article.id)
                .filter(self._active_article_filter())
                .filter(self._article_date() >= since)
                .filter((Article.title.ilike(pattern)) | (Article.content.ilike(pattern)))
                .all()
            )
            return {row[0] for row in rows}
        return set()

    @staticmethod
    def _article_date():
        return func.coalesce(Article.published_at, Article.fetched_at, Article.ingested_at)

    @staticmethod
    def _active_article_filter():
        return or_(Article.quality_status == None, Article.quality_status != "excluded")

    @staticmethod
    def _category_hits(text: str, categories: dict[str, list[str]]) -> list[str]:
        return [
            category
            for category, terms in categories.items()
            if any(term in text for term in terms)
        ]

    @staticmethod
    def _level(score: int) -> str:
        if score >= 85:
            return "critical"
        if score >= 65:
            return "high"
        if score >= 35:
            return "medium"
        if score > 0:
            return "low"
        return "none"

    @staticmethod
    def _empty_breakdown() -> dict:
        return {
            "political_volume": 0,
            "attack_language": 0,
            "negative_sentiment": 0,
            "cross_source_validation": 0,
            "high_reliability_sources": 0,
            "source_spread": 0,
            "watchlist_relevance": 0,
        }

    @staticmethod
    def _persona_weights(client_type) -> dict[str, float]:
        weights = {
            "volume": 1.0,
            "attack": 1.0,
            "sentiment": 1.0,
            "validation": 1.0,
            "reliability": 1.0,
            "spread": 1.0,
            "watchlist": 1.0,
        }
        if client_type == ClientType.POLITICAL_FIGURE:
            weights.update({"attack": 1.25, "sentiment": 1.3, "watchlist": 1.4, "volume": 0.8})
        elif client_type == ClientType.POLITICAL_PARTY:
            weights.update({"validation": 1.25, "spread": 1.2, "watchlist": 1.25, "sentiment": 0.9})
        elif client_type == ClientType.PR_AGENCY:
            weights.update({"spread": 1.35, "validation": 1.25, "volume": 1.15})
        elif client_type == ClientType.DIASPORA:
            weights.update({"attack": 0.75, "sentiment": 0.75, "validation": 1.2, "volume": 1.1})
        return weights

    @staticmethod
    def _has_political_context(text: str, article: Article) -> bool:
        if any(term in text for term in POLITICAL_CONTEXT_TERMS):
            return True
        for mention in article.entity_mentions:
            if mention.entity and mention.entity.entity_type.value in {"person", "organization"}:
                return True
        return False

    @staticmethod
    def _matches_watchlist_text(text: str, watchlist: list[ClientWatchlistItem]) -> bool:
        for item in watchlist:
            if item.entity_id:
                continue
            value = (item.value or item.label or "").lower().strip()
            if value and value in text:
                return True
        return False

    @staticmethod
    def _is_content_article(article: Article) -> bool:
        value = f"{article.title or ''} {article.url or ''}".lower()
        blocked_fragments = [
            "privacy",
            "politika-na-privatnost",
            "pravila-i-uslovi",
            "terms",
            "impressum",
            "impresum",
            "kontakt",
            "contact",
            "about",
            "za-nas",
            "za-birn",
            "live-tv",
            "najnovi-vesti",
            "latest-news",
            "resursi",
            "/feed",
            "/rss",
        ]
        if any(fragment in value for fragment in blocked_fragments):
            return False
        if article.title and article.source and article.title.strip().lower() == article.source.name.strip().lower():
            return False
        if article.url and article.url.rstrip("/").endswith(("time.mk/s/m", "time.mk/s")):
            return False
        path_parts = [
            part for part in urlparse(article.url or "").path.strip("/").split("/")
            if part
        ]
        category_paths = {
            "makedonija",
            "ekonomija",
            "svet",
            "region",
            "sport",
            "kultura",
            "zanimlivosti",
            "crna-hronika",
            "soopstenija",
            "studio",
        }
        if not article.published_at and len(path_parts) <= 2 and any(part in category_paths for part in path_parts):
            return False
        return True

    def _risk_events(
        self,
        clusters: list[StoryCluster],
        items: list[dict],
        attack_hits: dict[str, int],
    ) -> list[dict]:
        events = []
        for cluster in sorted(clusters, key=lambda row: (row.source_count, row.article_count), reverse=True)[:8]:
            severity = "high" if cluster.status == "validated" and cluster.source_count >= 3 else "medium" if cluster.source_count >= 2 else "low"
            events.append({
                "event_type": "story_cluster",
                "severity": severity,
                "title": cluster.title,
                "why_it_matters": cluster.summary,
                "source_count": cluster.source_count,
                "article_count": cluster.article_count,
                "recommended_action": (
                    "Prepare a sourced response or briefing note."
                    if severity in {"high", "medium"}
                    else "Monitor for pickup by additional sources."
                ),
            })
        for category, count in sorted(attack_hits.items(), key=lambda item: item[1], reverse=True)[:3]:
            events.append({
                "event_type": "attack_theme",
                "severity": "high" if count >= 5 else "medium",
                "title": category.replace("_", " ").title(),
                "why_it_matters": f"Detected in {count} recent relevant items.",
                "source_count": len({item["source_name"] for item in items if category in item.get("attack_categories", [])}),
                "article_count": count,
                "recommended_action": "Review affected entities and prepare rebuttal evidence.",
            })
        return events[:10]

    @staticmethod
    def _alert_suggestions(
        score: int,
        clusters: list[StoryCluster],
        attack_hits: dict[str, int],
        client: Client | None,
    ) -> list[dict]:
        suggestions = []
        threshold = 65 if client else 70
        if score >= threshold:
            suggestions.append({
                "type": "risk_threshold",
                "label": f"Alert when risk score stays above {threshold}",
                "criteria": {"risk_score_gte": threshold, "window_hours": 24},
            })
        if any(cluster.source_count >= 3 for cluster in clusters):
            suggestions.append({
                "type": "story_spread",
                "label": "Alert when a story spreads to 3+ sources",
                "criteria": {"source_count_gte": 3, "status": "validated"},
            })
        if attack_hits:
            top = max(attack_hits.items(), key=lambda item: item[1])
            suggestions.append({
                "type": "attack_theme",
                "label": f"Alert on rising {top[0].replace('_', ' ')} attacks",
                "criteria": {"attack_category": top[0], "count_gte": min(10, max(3, top[1] // 3))},
            })
        if client:
            suggestions.append({
                "type": "watchlist_negative_story",
                "label": "Alert when a watched entity appears in a negative validated story",
                "criteria": {"client_id": client.id, "validated": True, "sentiment_lte": -0.05},
            })
        return suggestions[:5]

    @staticmethod
    def _drivers(
        article_count: int,
        source_count: int,
        political_articles: int,
        watchlist_articles: int,
        attack_hits: dict[str, int],
        narrative_hits: dict[str, int],
        negative_ratio: float,
        validated_clusters: int,
        multi_source_clusters: int,
        high_reliability_sources: int,
    ) -> list[str]:
        drivers = []
        if article_count:
            drivers.append(f"{article_count} relevant articles across {source_count} sources.")
        if political_articles != article_count:
            drivers.append(f"{political_articles} articles have political/institutional context.")
        if watchlist_articles:
            drivers.append(f"{watchlist_articles} articles match client watchlist text.")
        if attack_hits:
            top_attack = max(attack_hits.items(), key=lambda item: item[1])
            drivers.append(f"Attack-language signal: {top_attack[0].replace('_', ' ')} in {top_attack[1]} items.")
        if narrative_hits:
            top_narrative = max(narrative_hits.items(), key=lambda item: item[1])
            drivers.append(f"Dominant narrative: {top_narrative[0].replace('_', ' ')}.")
        if negative_ratio >= 0.25:
            drivers.append(f"Negative entity sentiment is elevated at {round(negative_ratio * 100)}%.")
        if validated_clusters:
            drivers.append(f"{validated_clusters} validated cross-source story clusters.")
        elif multi_source_clusters:
            drivers.append(f"{multi_source_clusters} multi-source story clusters.")
        if high_reliability_sources:
            drivers.append(f"{high_reliability_sources} high-reliability sources involved.")
        return drivers or ["No significant political risk signals in this period."]
