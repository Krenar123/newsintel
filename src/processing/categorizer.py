"""
Article Categorizer — ML-based text classification.

Two-stage approach:
1. Keyword-based scoring (fast, works from day 1 with zero training data)
2. TF-IDF + Naive Bayes classifier (trained on accumulated articles)

The keyword scorer bootstraps the system. Once you have ~500+ categorized
articles, the ML model takes over and generalizes much better.
"""

import pickle
import re
from pathlib import Path
from typing import Optional
from dataclasses import dataclass

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.naive_bayes import MultinomialNB
from sklearn.pipeline import Pipeline
import structlog

logger = structlog.get_logger()


@dataclass
class CategoryResult:
    """Output of categorization."""
    category: str
    confidence: float
    all_scores: dict[str, float]   # category → confidence
    method: str                     # "keyword" or "ml"


# Default category keywords (can be overridden by country config)
DEFAULT_KEYWORDS = {
    "politics": [
        "government", "parliament", "election", "minister", "president",
        "law", "vote", "opposition", "coalition", "party", "senate",
        "congress", "policy", "legislation", "democracy", "diplomatic",
    ],
    "economy": [
        "economy", "business", "market", "stock", "gdp", "inflation",
        "trade", "investment", "unemployment", "bank", "budget", "tax",
        "revenue", "profit", "startup", "commerce", "finance",
    ],
    "society": [
        "education", "healthcare", "social", "community", "protest",
        "reform", "welfare", "housing", "poverty", "inequality",
        "migration", "culture", "religion",
    ],
    "crime": [
        "crime", "police", "arrest", "court", "trial", "prison",
        "murder", "theft", "fraud", "corruption", "investigation",
        "suspect", "verdict", "sentenced",
    ],
    "sports": [
        "football", "basketball", "soccer", "tennis", "match", "league",
        "championship", "tournament", "player", "coach", "goal", "score",
        "team", "athlete", "olympic",
    ],
    "tech": [
        "technology", "digital", "software", "ai", "artificial",
        "internet", "startup", "app", "cyber", "data", "algorithm",
        "robot", "innovation", "silicon",
    ],
    "health": [
        "health", "medical", "hospital", "disease", "vaccine", "doctor",
        "patient", "treatment", "pandemic", "virus", "mental health",
        "pharmaceutical", "clinical",
    ],
    "environment": [
        "climate", "environment", "pollution", "renewable", "energy",
        "carbon", "emissions", "recycling", "biodiversity", "forest",
        "sustainability", "green",
    ],
    "world": [
        "international", "global", "united nations", "nato", "eu",
        "foreign", "embassy", "summit", "treaty", "sanctions",
        "geopolitical", "bilateral",
    ],
    "culture": [
        "film", "movie", "music", "art", "theater", "festival",
        "book", "museum", "exhibition", "concert", "literature",
        "performance", "cultural",
    ],
}


class Categorizer:
    """
    Hybrid keyword + ML article categorizer.

    Use keyword mode from day 1, then train the ML model once you
    have enough labeled data for better generalization.
    """

    def __init__(
        self,
        keywords: Optional[dict[str, list[str]]] = None,
        model_path: Optional[Path] = None,
    ):
        self.keywords = keywords or DEFAULT_KEYWORDS
        self.model_path = model_path
        self.ml_pipeline: Optional[Pipeline] = None

        # Try to load trained model
        if model_path and Path(model_path).exists():
            self._load_model()

    def categorize_keyword(
        self, text: str, title: str = ""
    ) -> CategoryResult:
        """
        Categorize using keyword frequency scoring.

        Fast, deterministic, works with zero training data.
        Good enough for bootstrapping.
        """
        combined = f"{title} {title} {text}".lower()  # title weighted 2x
        scores: dict[str, float] = {}

        for category, keywords in self.keywords.items():
            score = 0.0
            for keyword in keywords:
                # Count occurrences, normalize by text length
                count = len(re.findall(
                    r'\b' + re.escape(keyword) + r'\b', combined
                ))
                score += count

            # Normalize score
            word_count = max(len(combined.split()), 1)
            scores[category] = score / (word_count ** 0.5)  # sqrt normalization

        if not scores or max(scores.values()) == 0:
            return CategoryResult(
                category="general",
                confidence=0.0,
                all_scores=scores,
                method="keyword",
            )

        best_cat = max(scores, key=scores.get)
        total = sum(scores.values()) or 1.0
        confidence = scores[best_cat] / total

        return CategoryResult(
            category=best_cat,
            confidence=round(confidence, 3),
            all_scores={k: round(v / total, 3) for k, v in scores.items()},
            method="keyword",
        )

    def categorize_ml(self, text: str, title: str = "") -> CategoryResult:
        """
        Categorize using trained TF-IDF + Naive Bayes model.

        Only available after training with train_model().
        Falls back to keyword method if model isn't trained.
        """
        if self.ml_pipeline is None:
            return self.categorize_keyword(text, title)

        combined = f"{title} {text}"

        try:
            predicted = self.ml_pipeline.predict([combined])[0]
            probabilities = self.ml_pipeline.predict_proba([combined])[0]
            classes = self.ml_pipeline.classes_

            scores = {
                cls: round(float(prob), 3)
                for cls, prob in zip(classes, probabilities)
            }
            confidence = max(probabilities)

            return CategoryResult(
                category=predicted,
                confidence=round(float(confidence), 3),
                all_scores=scores,
                method="ml",
            )
        except Exception as e:
            logger.error("ml_categorize_failed", error=str(e))
            return self.categorize_keyword(text, title)

    def categorize(self, text: str, title: str = "") -> CategoryResult:
        """
        Main entry point — uses ML model if available, else keywords.
        """
        if self.ml_pipeline is not None:
            return self.categorize_ml(text, title)
        return self.categorize_keyword(text, title)

    def train_model(
        self, texts: list[str], labels: list[str], save: bool = True
    ) -> dict:
        """
        Train the ML classification model on labeled articles.

        Args:
            texts:  List of "title + content" strings
            labels: Corresponding category labels
            save:   Whether to save the model to disk

        Returns:
            Training metrics dict
        """
        from sklearn.model_selection import cross_val_score

        logger.info("training_categorizer", samples=len(texts))

        self.ml_pipeline = Pipeline([
            ("tfidf", TfidfVectorizer(
                max_features=10000,
                ngram_range=(1, 2),
                min_df=2,
                max_df=0.95,
                sublinear_tf=True,
            )),
            ("clf", MultinomialNB(alpha=0.1)),
        ])

        self.ml_pipeline.fit(texts, labels)

        # Cross-validation score
        scores = cross_val_score(
            self.ml_pipeline, texts, labels, cv=min(5, len(set(labels))),
            scoring="accuracy"
        )

        metrics = {
            "accuracy_mean": round(float(scores.mean()), 3),
            "accuracy_std": round(float(scores.std()), 3),
            "num_samples": len(texts),
            "num_categories": len(set(labels)),
            "categories": list(set(labels)),
        }

        logger.info("model_trained", **metrics)

        if save and self.model_path:
            self._save_model()

        return metrics

    def _save_model(self):
        """Persist trained model to disk."""
        if self.ml_pipeline and self.model_path:
            Path(self.model_path).parent.mkdir(parents=True, exist_ok=True)
            with open(self.model_path, "wb") as f:
                pickle.dump(self.ml_pipeline, f)
            logger.info("model_saved", path=str(self.model_path))

    def _load_model(self):
        """Load trained model from disk."""
        try:
            with open(self.model_path, "rb") as f:
                self.ml_pipeline = pickle.load(f)
            logger.info("model_loaded", path=str(self.model_path))
        except Exception as e:
            logger.warning("model_load_failed", error=str(e))
            self.ml_pipeline = None
