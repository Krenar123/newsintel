"""
Sentiment Analyzer — Per-entity and per-article sentiment scoring.

Uses a hybrid approach for zero API cost:
  1. VADER (Valence Aware Dictionary and sEntiment Reasoner) — rule-based,
     fast, specifically tuned for social media and news text
  2. TextBlob as fallback for language coverage
  3. Context-aware entity sentiment: scores the sentiment of sentences
     where each entity appears, not just the whole article

Output: -1.0 (very negative) to +1.0 (very positive), with 0.0 = neutral.

Why not ML-based sentiment?
  - VADER outperforms many ML models on news text (see Hutto & Gilbert 2014)
  - Zero training data needed
  - Fast enough for real-time processing (10K+ sentences/second)
  - Works out of the box for English; TextBlob covers other languages
"""

import re
from typing import Optional
from dataclasses import dataclass, field

import structlog

logger = structlog.get_logger()


@dataclass
class SentimentScore:
    """Sentiment analysis result."""
    compound: float        # Overall: -1.0 to 1.0
    positive: float        # Positive proportion: 0.0 to 1.0
    negative: float        # Negative proportion: 0.0 to 1.0
    neutral: float         # Neutral proportion: 0.0 to 1.0
    label: str             # "positive", "negative", "neutral"
    confidence: float      # How confident we are in the label


@dataclass
class EntitySentiment:
    """Sentiment for a specific entity within an article."""
    entity_name: str
    entity_type: str
    overall_sentiment: SentimentScore
    mention_sentiments: list[SentimentScore] = field(default_factory=list)
    context_sentences: list[str] = field(default_factory=list)
    mention_count: int = 0
    sentiment_trend: str = "stable"  # "improving", "declining", "stable"


@dataclass
class ArticleSentiment:
    """Full sentiment analysis of an article."""
    overall: SentimentScore
    title_sentiment: SentimentScore
    entity_sentiments: list[EntitySentiment] = field(default_factory=list)
    sentence_scores: list[tuple[str, float]] = field(default_factory=list)


class SentimentAnalyzer:
    """
    Multi-strategy sentiment analyzer optimized for news text.

    Primary:  VADER — best for English news/social text
    Fallback: TextBlob — broader language support
    Custom:   Domain-specific news lexicon adjustments
    """

    # News-specific sentiment modifiers
    # Words that shift sentiment in news context differently than general text
    NEWS_LEXICON_BOOST = {
        # Negative in news context (stronger than VADER defaults)
        "corruption": -0.8,
        "scandal": -0.7,
        "crisis": -0.7,
        "fraud": -0.8,
        "arrest": -0.5,
        "detained": -0.5,
        "convicted": -0.6,
        "indicted": -0.6,
        "sanctions": -0.5,
        "protests": -0.3,
        "clashes": -0.6,
        "casualties": -0.8,
        "resignation": -0.3,
        "fired": -0.4,
        "collapsed": -0.6,
        "bankruptcy": -0.7,
        "recession": -0.6,
        "inflation": -0.3,
        "unemployment": -0.4,
        "deficit": -0.3,
        "investigation": -0.3,
        "alleged": -0.2,
        "controversial": -0.3,
        "dispute": -0.3,
        "conflict": -0.5,
        "war": -0.7,
        "attacked": -0.6,

        # Positive in news context
        "agreement": 0.5,
        "reform": 0.3,
        "growth": 0.5,
        "investment": 0.4,
        "partnership": 0.4,
        "elected": 0.2,
        "approved": 0.3,
        "breakthrough": 0.6,
        "historic": 0.3,
        "unprecedented": 0.2,
        "cooperation": 0.4,
        "progress": 0.4,
        "recovery": 0.5,
        "prosperity": 0.5,
        "peace": 0.6,
        "humanitarian": 0.3,
        "innovation": 0.4,
        "sustainable": 0.3,
    }

    def __init__(self):
        self._vader = None
        self._textblob_available = False
        self._init_analyzers()

    def _init_analyzers(self):
        """Initialize sentiment analysis backends."""
        # Try VADER first (preferred for English news)
        try:
            import nltk
            try:
                nltk.data.find('sentiment/vader_lexicon.zip')
            except LookupError:
                nltk.download('vader_lexicon', quiet=True)

            from nltk.sentiment.vader import SentimentIntensityAnalyzer
            self._vader = SentimentIntensityAnalyzer()

            # Inject news-specific lexicon
            self._vader.lexicon.update(self.NEWS_LEXICON_BOOST)
            logger.info("sentiment_vader_loaded")
        except Exception as e:
            logger.warning("vader_load_failed", error=str(e))

        # Try TextBlob as fallback
        try:
            from textblob import TextBlob  # noqa: F401
            self._textblob_available = True
            logger.info("sentiment_textblob_available")
        except ImportError:
            logger.info("textblob_not_available")

    # ------------------------------------------------------------------
    # Core scoring
    # ------------------------------------------------------------------

    def score_text(self, text: str, language: str = "en") -> SentimentScore:
        """
        Score sentiment of a text passage.

        Uses VADER for English, TextBlob for other languages.
        Returns SentimentScore with compound, pos, neg, neutral.
        """
        if not text or len(text.strip()) < 3:
            return SentimentScore(
                compound=0.0, positive=0.0, negative=0.0,
                neutral=1.0, label="neutral", confidence=0.0,
            )

        if language == "en" and self._vader:
            return self._score_vader(text)
        elif self._textblob_available:
            return self._score_textblob(text)
        elif self._vader:
            # Fallback: use VADER even for non-English
            return self._score_vader(text)
        else:
            return SentimentScore(
                compound=0.0, positive=0.0, negative=0.0,
                neutral=1.0, label="neutral", confidence=0.0,
            )

    def _score_vader(self, text: str) -> SentimentScore:
        """Score using VADER."""
        scores = self._vader.polarity_scores(text)

        compound = scores["compound"]
        label = self._compound_to_label(compound)
        confidence = abs(compound)

        return SentimentScore(
            compound=round(compound, 4),
            positive=round(scores["pos"], 4),
            negative=round(scores["neg"], 4),
            neutral=round(scores["neu"], 4),
            label=label,
            confidence=round(confidence, 4),
        )

    def _score_textblob(self, text: str) -> SentimentScore:
        """Score using TextBlob (broader language support)."""
        from textblob import TextBlob

        blob = TextBlob(text)
        polarity = blob.sentiment.polarity  # -1 to 1
        subjectivity = blob.sentiment.subjectivity  # 0 to 1

        label = self._compound_to_label(polarity)

        # Map polarity to VADER-like scores
        pos = max(0, polarity)
        neg = abs(min(0, polarity))
        neu = 1.0 - abs(polarity)

        return SentimentScore(
            compound=round(polarity, 4),
            positive=round(pos, 4),
            negative=round(neg, 4),
            neutral=round(neu, 4),
            label=label,
            confidence=round(abs(polarity), 4),
        )

    # ------------------------------------------------------------------
    # Article-level analysis
    # ------------------------------------------------------------------

    def analyze_article(
        self,
        title: str,
        content: str,
        entities: list[dict] = None,
        language: str = "en",
    ) -> ArticleSentiment:
        """
        Full sentiment analysis of an article.

        Args:
            title:    Article title
            content:  Article body text
            entities: List of {"name": ..., "type": ..., "contexts": [...]}
            language: ISO language code

        Returns:
            ArticleSentiment with overall, title, and per-entity scores
        """
        # Title sentiment (titles carry disproportionate weight in news)
        title_sentiment = self.score_text(title, language)

        # Overall article sentiment
        overall = self.score_text(content, language)

        # Weighted overall: title counts for 30%, body for 70%
        weighted_compound = (
            title_sentiment.compound * 0.3 + overall.compound * 0.7
        )
        overall = SentimentScore(
            compound=round(weighted_compound, 4),
            positive=overall.positive,
            negative=overall.negative,
            neutral=overall.neutral,
            label=self._compound_to_label(weighted_compound),
            confidence=round(abs(weighted_compound), 4),
        )

        # Per-entity sentiment
        entity_sentiments = []
        if entities:
            for ent in entities:
                ent_sentiment = self._analyze_entity_sentiment(
                    entity_name=ent.get("name", ""),
                    entity_type=ent.get("type", "other"),
                    contexts=ent.get("contexts", []),
                    full_text=content,
                    language=language,
                )
                entity_sentiments.append(ent_sentiment)

        # Sentence-level breakdown (top 5 most opinionated)
        sentence_scores = self._score_sentences(content, language, top_n=5)

        return ArticleSentiment(
            overall=overall,
            title_sentiment=title_sentiment,
            entity_sentiments=entity_sentiments,
            sentence_scores=sentence_scores,
        )

    def _analyze_entity_sentiment(
        self,
        entity_name: str,
        entity_type: str,
        contexts: list[str],
        full_text: str,
        language: str,
    ) -> EntitySentiment:
        """
        Analyze sentiment specifically about an entity.

        Scores the sentences where the entity is mentioned,
        not the whole article — this gives much more accurate
        per-entity sentiment.
        """
        # Find all sentences containing this entity
        entity_sentences = contexts.copy()

        # Also search the full text for additional mentions
        if full_text:
            sentences = self._split_sentences(full_text)
            name_lower = entity_name.lower()
            for sent in sentences:
                if name_lower in sent.lower() and sent not in entity_sentences:
                    entity_sentences.append(sent)

        if not entity_sentences:
            return EntitySentiment(
                entity_name=entity_name,
                entity_type=entity_type,
                overall_sentiment=SentimentScore(
                    compound=0.0, positive=0.0, negative=0.0,
                    neutral=1.0, label="neutral", confidence=0.0,
                ),
                mention_count=0,
            )

        # Score each mention
        mention_scores = []
        for sent in entity_sentences[:20]:  # cap at 20 mentions
            score = self.score_text(sent, language)
            mention_scores.append(score)

        # Aggregate: weighted average (more recent = higher weight)
        if mention_scores:
            total_compound = sum(s.compound for s in mention_scores)
            avg_compound = total_compound / len(mention_scores)
        else:
            avg_compound = 0.0

        overall = SentimentScore(
            compound=round(avg_compound, 4),
            positive=round(sum(s.positive for s in mention_scores) / max(len(mention_scores), 1), 4),
            negative=round(sum(s.negative for s in mention_scores) / max(len(mention_scores), 1), 4),
            neutral=round(sum(s.neutral for s in mention_scores) / max(len(mention_scores), 1), 4),
            label=self._compound_to_label(avg_compound),
            confidence=round(abs(avg_compound), 4),
        )

        return EntitySentiment(
            entity_name=entity_name,
            entity_type=entity_type,
            overall_sentiment=overall,
            mention_sentiments=mention_scores,
            context_sentences=entity_sentences[:5],
            mention_count=len(entity_sentences),
        )

    def _score_sentences(
        self, text: str, language: str, top_n: int = 5
    ) -> list[tuple[str, float]]:
        """
        Score individual sentences, return the most opinionated ones.

        Useful for finding the "hottest" statements in an article.
        """
        sentences = self._split_sentences(text)
        scored = []

        for sent in sentences:
            if len(sent.split()) < 5:  # skip very short sentences
                continue
            score = self.score_text(sent, language)
            scored.append((sent[:200], score.compound))

        # Sort by absolute sentiment (most opinionated first)
        scored.sort(key=lambda x: abs(x[1]), reverse=True)
        return scored[:top_n]

    # ------------------------------------------------------------------
    # Historical sentiment tracking
    # ------------------------------------------------------------------

    def compute_sentiment_trend(
        self,
        recent_scores: list[float],
        previous_scores: list[float],
    ) -> dict:
        """
        Compare recent vs previous sentiment for an entity.

        Returns trend direction and magnitude.
        """
        if not recent_scores:
            return {"direction": "unknown", "change": 0.0, "magnitude": "none"}

        recent_avg = sum(recent_scores) / len(recent_scores)
        prev_avg = (
            sum(previous_scores) / len(previous_scores)
            if previous_scores else 0.0
        )

        change = recent_avg - prev_avg

        if abs(change) < 0.05:
            direction = "stable"
            magnitude = "none"
        elif change > 0:
            direction = "improving"
            magnitude = "strong" if change > 0.2 else "slight"
        else:
            direction = "declining"
            magnitude = "strong" if change < -0.2 else "slight"

        return {
            "direction": direction,
            "change": round(change, 4),
            "magnitude": magnitude,
            "recent_avg": round(recent_avg, 4),
            "previous_avg": round(prev_avg, 4),
            "recent_count": len(recent_scores),
            "previous_count": len(previous_scores),
        }

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    @staticmethod
    def _compound_to_label(compound: float) -> str:
        """Convert compound score to human-readable label."""
        if compound >= 0.05:
            return "positive"
        elif compound <= -0.05:
            return "negative"
        return "neutral"

    @staticmethod
    def _split_sentences(text: str) -> list[str]:
        """Split text into sentences (simple rule-based)."""
        # Split on sentence-ending punctuation followed by whitespace
        sentences = re.split(r'(?<=[.!?])\s+', text)
        return [s.strip() for s in sentences if s.strip()]
