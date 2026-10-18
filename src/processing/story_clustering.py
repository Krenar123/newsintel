"""Cross-source story clustering and validation signals."""

import datetime
from collections import defaultdict
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from sqlalchemy.orm import Session
from sqlalchemy import or_

from src.models.database import (
    Article,
    Source,
    StoryCluster,
    StoryClusterArticle,
)
from src.processing.entities import EntityExtractor


@dataclass
class ClusterCandidate:
    article: Article
    key: str
    token_set: set[str]
    cluster_index: int | None = None


@dataclass
class WorkingCluster:
    key: str
    articles: list[tuple[Article, float]] = field(default_factory=list)


class StoryClusterer:
    """Build story clusters from recent article titles and source metadata."""

    def __init__(self, session: Session):
        self.session = session

    def rebuild(
        self,
        country_code: str = "mk",
        days: int = 14,
        limit: int = 1000,
    ) -> dict:
        since = datetime.datetime.utcnow() - datetime.timedelta(days=days)
        articles = (
            self.session.query(Article)
            .join(Source, Source.id == Article.source_id)
            .filter(Source.country_code == country_code)
            .filter(or_(Article.quality_status == None, Article.quality_status != "excluded"))
            .filter(
                (Article.published_at >= since)
                | ((Article.published_at == None) & (Article.fetched_at >= since))
            )
            .order_by(Article.published_at.desc().nullslast(), Article.fetched_at.desc())
            .limit(limit)
            .all()
        )

        self._clear_existing(country_code)
        candidates = [
            ClusterCandidate(
                article=article,
                key=self._normalize_title(article.title),
                token_set=set(self._normalize_title(article.title).split()),
            )
            for article in articles
            if article.title and len(article.title.strip()) >= 12
        ]
        clusters = self._cluster_candidates(candidates)
        saved = 0
        links = 0
        for cluster in clusters:
            if not cluster.articles:
                continue
            self._save_cluster(country_code, cluster)
            saved += 1
            links += len(cluster.articles)

        self.session.commit()
        return {
            "articles_considered": len(candidates),
            "clusters_created": saved,
            "cluster_links": links,
            "title_comparisons": self._title_comparisons,
        }

    def _clear_existing(self, country_code: str):
        cluster_ids = [
            row[0]
            for row in self.session.query(StoryCluster.id)
            .filter(StoryCluster.country_code == country_code)
            .all()
        ]
        if not cluster_ids:
            return
        self.session.query(StoryClusterArticle).filter(
            StoryClusterArticle.cluster_id.in_(cluster_ids)
        ).delete(synchronize_session=False)
        self.session.query(StoryCluster).filter(
            StoryCluster.id.in_(cluster_ids)
        ).delete(synchronize_session=False)
        self.session.flush()

    def _cluster_candidates(self, candidates: list[ClusterCandidate]) -> list[WorkingCluster]:
        clusters: list[WorkingCluster] = []
        token_index: dict[str, set[int]] = defaultdict(set)
        self._title_comparisons = 0
        for candidate in candidates:
            if not candidate.key:
                continue
            best_index = None
            best_score = 0.0
            index_tokens = {token for token in candidate.token_set if len(token) >= 4}
            if not index_tokens:
                index_tokens = candidate.token_set
            possible_indices: set[int] = set()
            for token in index_tokens:
                possible_indices.update(token_index.get(token, set()))

            for index in possible_indices:
                cluster = clusters[index]
                self._title_comparisons += 1
                score = self._similarity(candidate, cluster)
                if score > best_score:
                    best_score = score
                    best_index = index
            if best_index is not None and best_score >= 0.62:
                clusters[best_index].articles.append((candidate.article, best_score))
            else:
                cluster_index = len(clusters)
                clusters.append(WorkingCluster(
                    key=candidate.key,
                    articles=[(candidate.article, 1.0)],
                ))
                for token in index_tokens:
                    token_index[token].add(cluster_index)
        return clusters

    @staticmethod
    def _similarity(candidate: ClusterCandidate, cluster: WorkingCluster) -> float:
        title_score = SequenceMatcher(None, candidate.key, cluster.key).ratio()
        cluster_tokens = set(cluster.key.split())
        overlap = (
            len(candidate.token_set & cluster_tokens) / max(1, len(candidate.token_set | cluster_tokens))
        )
        return max(title_score, (title_score * 0.7) + (overlap * 0.3))

    def _save_cluster(self, country_code: str, cluster: WorkingCluster):
        articles = [article for article, _score in cluster.articles]
        evidence_articles = [
            article for article in articles
            if not article.source or article.source.source_type != "aggregator"
        ] or articles
        sources = {article.source_id for article in evidence_articles}
        reliabilities = [
            article.source.reliability_score or 0
            for article in evidence_articles
            if article.source
        ]
        dates = [
            article.published_at or article.fetched_at or article.ingested_at
            for article in articles
            if article.published_at or article.fetched_at or article.ingested_at
        ]
        source_count = len(sources)
        high_reliability = len({
            article.source_id
            for article in evidence_articles
            if article.source and (article.source.reliability_score or 0) >= 0.75
        })
        status = (
            "validated"
            if source_count >= 3 and high_reliability >= 2
            else "multi_source"
            if source_count >= 2
            else "single_source"
        )
        lead = sorted(
            evidence_articles,
            key=lambda article: (
                article.published_at or article.fetched_at or article.ingested_at or datetime.datetime.min
            ),
            reverse=True,
        )[0]
        row = StoryCluster(
            country_code=country_code,
            title=lead.title[:500],
            canonical_key=cluster.key[:500],
            status=status,
            article_count=len(articles),
            source_count=source_count,
            high_reliability_source_count=high_reliability,
            average_reliability=(sum(reliabilities) / len(reliabilities)) if reliabilities else 0,
            first_published_at=min(dates) if dates else None,
            last_published_at=max(dates) if dates else None,
            summary=self._summary(status, source_count, high_reliability),
        )
        self.session.add(row)
        self.session.flush()
        for article, score in cluster.articles:
            self.session.add(StoryClusterArticle(
                cluster_id=row.id,
                article_id=article.id,
                source_id=article.source_id,
                similarity_score=score,
            ))

    @staticmethod
    def _summary(status: str, source_count: int, high_reliability: int) -> str:
        if status == "validated":
            return f"Reported by {source_count} sources, including {high_reliability} high-reliability sources."
        if status == "multi_source":
            return f"Reported by {source_count} sources."
        return "Single-source report. Verify independently before relying on it."

    @staticmethod
    def _normalize_title(value: str) -> str:
        normalized = EntityExtractor._canonicalize(value or "")
        stop = {
            "на", "во", "со", "за", "од", "до", "и", "или", "дека", "ќе",
            "the", "a", "an", "of", "to", "in", "for", "and",
        }
        tokens = [token for token in normalized.split() if token not in stop and len(token) > 1]
        return " ".join(tokens)
