"""
Processing Pipeline — Orchestrates the full article processing workflow.

For each unprocessed article:
  1. Summarize (extractive, free)
  2. Categorize (keyword/ML, free)
  3. Extract entities (spaCy NER, free)
  4. Store results in database
  5. Optionally generate AI summary (paid)

All core processing is local and free. Claude API is only called
when explicitly enabled for premium summaries.
"""

import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session
from sqlalchemy import or_
import structlog

from src.models.database import (
    Article, Summary, Entity, EntityMention, ArticleCategory,
    Source, SummaryType, EntityType,
)
from src.processing.summarizer import Summarizer
from src.processing.categorizer import Categorizer
from src.processing.entities import EntityExtractor
from src.processing.sentiment import SentimentAnalyzer
from src.processing.alerts import AlertEngine, NotificationDispatcher
from src.ingestion.rss_fetcher import RawArticle, normalize_url
from src.search.normalization import search_blob

logger = structlog.get_logger()


class ProcessingPipeline:
    """
    Full article processing pipeline.

    Coordinates summarization, categorization, and entity extraction
    for each article. Handles database storage and deduplication.
    """

    def __init__(
        self,
        session: Session,
        enable_ai: bool = False,
        api_key: Optional[str] = None,
        model_path: Optional[Path] = None,
        languages: list[str] = None,
    ):
        self.session = session
        self.summarizer = Summarizer(enable_ai=enable_ai, api_key=api_key)
        self.categorizer = Categorizer(
            model_path=model_path / "categorizer.pkl" if model_path else None
        )
        self.entity_extractor = EntityExtractor(languages=languages or ["en"])
        self.sentiment_analyzer = SentimentAnalyzer()
        self.alert_engine = AlertEngine(session)

    # ------------------------------------------------------------------
    # Ingestion: Raw articles → database
    # ------------------------------------------------------------------

    def ingest_articles(
        self,
        raw_articles: list[RawArticle],
        stop_after_consecutive_duplicates: Optional[int] = None,
    ) -> dict:
        """
        Ingest raw articles into the database.

        Handles deduplication via content hash. Returns stats.
        """
        stats = {
            "total": len(raw_articles),
            "checked": 0,
            "new": 0,
            "duplicate": 0,
            "duplicate_fuzzy": 0,
            "error": 0,
            "duplicate_streak": 0,
            "stopped_early": False,
        }
        duplicate_streak = 0

        for raw in raw_articles:
            try:
                stats["checked"] += 1
                raw.url = normalize_url(raw.url)
                raw.compute_hash()
                # Check for duplicate by URL/hash first, then same-source fuzzy title.
                existing = self._find_duplicate_article(raw)
                if existing:
                    if existing == "fuzzy":
                        stats["duplicate_fuzzy"] += 1
                    else:
                        stats["duplicate"] += 1
                    duplicate_streak += 1
                    stats["duplicate_streak"] = duplicate_streak
                    if (
                        stop_after_consecutive_duplicates
                        and duplicate_streak >= stop_after_consecutive_duplicates
                    ):
                        stats["stopped_early"] = True
                        break
                    continue

                # Find or create source
                source = self._get_or_create_source(raw)

                # Create article record
                article = Article(
                    source_id=source.id,
                    url=raw.url,
                    title=raw.title,
                    content=raw.content,
                    search_text=search_blob(raw.title, raw.content, raw.author),
                    author=raw.author,
                    language=raw.language,
                    published_at=raw.published_at,
                    fetched_at=raw.fetched_at,
                    word_count=len(raw.content.split()) if raw.content else 0,
                    content_hash=raw.content_hash,
                    raw_html=raw.raw_html,
                    image_url=raw.image_url,
                    ingestion_method=raw.ingestion_method,
                    platform=raw.platform,
                    external_id=raw.external_id,
                    platform_account_id=raw.platform_account_id,
                    platform_account_name=raw.platform_account_name,
                    is_processed=False,
                )
                self.session.add(article)
                self.session.flush()  # get article.id
                source.last_fetched_at = raw.fetched_at
                stats["new"] += 1
                duplicate_streak = 0
                stats["duplicate_streak"] = 0

            except Exception as e:
                logger.error(
                    "ingest_error", url=raw.url, error=str(e)
                )
                stats["error"] += 1
                duplicate_streak = 0
                stats["duplicate_streak"] = 0
                self.session.rollback()

        self.session.commit()
        logger.info("ingestion_complete", **stats)
        return stats

    # ------------------------------------------------------------------
    # Processing: Summarize + Categorize + Extract entities
    # ------------------------------------------------------------------

    def process_unprocessed(
        self,
        batch_size: int = 100,
        translate_to: Optional[str] = None,
    ) -> dict:
        """
        Process all unprocessed articles in the database.

        For each article:
          1. Generate extractive summary (free)
          2. Categorize (keyword/ML, free)
          3. Extract entities (spaCy, free)
          4. Optionally generate AI summary
        """
        articles = (
            self.session.query(Article)
            .filter(Article.is_processed == False)
            .filter(or_(Article.quality_status == None, Article.quality_status != "excluded"))
            .order_by(Article.ingested_at.desc())
            .limit(batch_size)
            .all()
        )

        stats = {"processed": 0, "errors": 0}
        logger.info("processing_batch", count=len(articles))

        for article in articles:
            try:
                self._process_single(article, translate_to)
                article.is_processed = True
                stats["processed"] += 1
            except Exception as e:
                logger.error(
                    "processing_error",
                    article_id=article.id,
                    error=str(e),
                )
                article.processing_error = str(e)
                stats["errors"] += 1

            # Commit per article to avoid losing work
            self.session.commit()

        logger.info("processing_complete", **stats)

        # 5. Evaluate alerts against newly processed articles
        if stats["processed"] > 0:
            try:
                alert_results = self.alert_engine.evaluate_all()
                triggered = [r for r in alert_results if r.triggered]
                if triggered:
                    logger.info(
                        "alerts_triggered",
                        count=len(triggered),
                        names=[r.alert_name for r in triggered],
                    )
                stats["alerts_triggered"] = len(triggered)
            except Exception as e:
                logger.error("alert_evaluation_failed", error=str(e))
                stats["alerts_triggered"] = 0

        return stats

    def _process_single(
        self, article: Article, translate_to: Optional[str] = None
    ):
        """Process a single article through the full pipeline."""
        text = article.content or ""
        if not text:
            return

        # 1. Extractive summary (free)
        summary_result = self.summarizer.summarize(
            text=text,
            language=article.language,
            sentence_count=3,
            article_title=article.title,
            translate_to=translate_to,
        )

        summary = Summary(
            article_id=article.id,
            summary_type=SummaryType(summary_result.summary_type),
            text=summary_result.text,
            language=summary_result.output_language,
            sentence_count=summary_result.sentence_count,
        )
        self.session.add(summary)

        # 2. Categorize
        cat_result = self.categorizer.categorize(text, article.title)

        # Primary category
        primary_cat = ArticleCategory(
            article_id=article.id,
            category=cat_result.category,
            confidence=cat_result.confidence,
            is_primary=True,
        )
        self.session.add(primary_cat)

        # Secondary categories (confidence > 0.15)
        for cat_name, score in cat_result.all_scores.items():
            if cat_name != cat_result.category and score > 0.15:
                secondary = ArticleCategory(
                    article_id=article.id,
                    category=cat_name,
                    confidence=score,
                    is_primary=False,
                )
                self.session.add(secondary)

        # 3. Extract entities
        ner_result = self.entity_extractor.extract(
            text=text, language=article.language
        )

        for extracted in ner_result.entities:
            entity = self._get_or_create_entity(extracted)

            # Create mention link
            mention = EntityMention(
                entity_id=entity.id,
                article_id=article.id,
                mention_count=extracted.mention_count,
                context_snippet=(
                    extracted.context_snippets[0]
                    if extracted.context_snippets
                    else None
                ),
            )
            self.session.add(mention)

            # Update entity stats
            entity.total_mentions += extracted.mention_count
            entity.last_seen_at = datetime.datetime.utcnow()

            # 4. Score sentiment for this entity's context
            if extracted.context_snippets:
                ent_sentiment = self.sentiment_analyzer.score_text(
                    " ".join(extracted.context_snippets),
                    language=article.language,
                )
                mention.sentiment_score = ent_sentiment.compound

        self.session.flush()

    # ------------------------------------------------------------------
    # Helper: Source management
    # ------------------------------------------------------------------

    def _get_or_create_source(self, raw: RawArticle) -> Source:
        """Find existing source or create a new one."""
        source = (
            self.session.query(Source)
            .filter(Source.url == raw.source_url)
            .first()
        )
        if not source:
            source = Source(
                name=raw.source_name,
                url=raw.source_url,
                country_code=raw.source_country_code,
                language=raw.language,
                reliability_score=raw.source_reliability_score,
                source_type=raw.source_type,
                political_leaning=raw.source_political_leaning,
                ownership=raw.source_ownership,
            )
            self.session.add(source)
            self.session.flush()
        else:
            source.country_code = raw.source_country_code or source.country_code
            source.source_type = raw.source_type or source.source_type
            source.reliability_score = raw.source_reliability_score
            source.political_leaning = raw.source_political_leaning or source.political_leaning
            source.ownership = raw.source_ownership or source.ownership
        return source

    def _find_duplicate_article(self, raw: RawArticle):
        """Return an existing article or 'fuzzy' when raw appears duplicate."""
        existing = (
            self.session.query(Article)
            .filter(
                (Article.url == raw.url)
                | (Article.content_hash == raw.content_hash)
            )
            .first()
        )
        if existing:
            return existing

        if raw.platform and raw.external_id:
            existing = (
                self.session.query(Article)
                .filter(
                    Article.platform == raw.platform,
                    Article.external_id == raw.external_id,
                )
                .first()
            )
            if existing:
                return existing

        source = (
            self.session.query(Source)
            .filter(Source.url == raw.source_url)
            .first()
        )
        if not source or not raw.title:
            return None

        since = (raw.published_at or raw.fetched_at) - datetime.timedelta(days=7)
        candidates = (
            self.session.query(Article)
            .filter(
                Article.source_id == source.id,
                ((Article.published_at != None) & (Article.published_at >= since))
                | ((Article.fetched_at != None) & (Article.fetched_at >= since)),
            )
            .order_by(Article.fetched_at.desc())
            .limit(50)
            .all()
        )
        raw_title = self._normalize_title(raw.title)
        raw_content = self._normalize_title((raw.content or "")[:800])

        for article in candidates:
            title_score = SequenceMatcher(
                None, raw_title, self._normalize_title(article.title)
            ).ratio()
            if title_score >= 0.92:
                return "fuzzy"

            if raw_content and article.content:
                content_score = SequenceMatcher(
                    None,
                    raw_content,
                    self._normalize_title(article.content[:800]),
                ).ratio()
                if title_score >= 0.82 and content_score >= 0.75:
                    return "fuzzy"

        return None

    @staticmethod
    def _normalize_title(value: str) -> str:
        return " ".join(
            "".join(ch.lower() if ch.isalnum() else " " for ch in value).split()
        )

    # ------------------------------------------------------------------
    # Helper: Entity deduplication
    # ------------------------------------------------------------------

    def _get_or_create_entity(self, extracted) -> Entity:
        """Find existing entity or create a new one (deduplicated)."""
        entity_type = EntityType(extracted.entity_type)

        entity = (
            self.session.query(Entity)
            .filter(
                Entity.canonical_name == extracted.canonical_name,
                Entity.entity_type == entity_type,
            )
            .first()
        )

        if not entity:
            entity = Entity(
                name=extracted.name,
                canonical_name=extracted.canonical_name,
                search_text=search_blob(extracted.name, extracted.canonical_name),
                entity_type=entity_type,
            )
            self.session.add(entity)
            self.session.flush()
        elif not entity.search_text:
            entity.search_text = search_blob(entity.name, entity.canonical_name)

        return entity

    # ------------------------------------------------------------------
    # Training: Build ML categorizer from accumulated data
    # ------------------------------------------------------------------

    def train_categorizer(self, min_samples: int = 100) -> Optional[dict]:
        """
        Train the ML categorizer on articles that have been keyword-categorized.

        Call this once you have enough data (500+ articles recommended).
        """
        results = (
            self.session.query(
                Article.title, Article.content, ArticleCategory.category
            )
            .join(ArticleCategory)
            .filter(ArticleCategory.is_primary == True)
            .filter(ArticleCategory.confidence > 0.3)
            .all()
        )

        if len(results) < min_samples:
            logger.warning(
                "insufficient_training_data",
                count=len(results),
                required=min_samples,
            )
            return None

        texts = [f"{r[0]} {r[1]}" for r in results]
        labels = [r[2] for r in results]

        return self.categorizer.train_model(texts, labels)
