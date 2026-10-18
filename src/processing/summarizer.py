"""
Article Summarizer — Dual-mode: extractive (free) and abstractive (AI).

Extractive summarization uses sumy (TextRank algorithm) — runs locally,
costs nothing, and works in any language. Good enough for 90% of use cases.

Abstractive summarization uses Claude API (Haiku) for premium quality.
Only called when explicitly enabled.
"""

import re
from typing import Optional
from dataclasses import dataclass

import structlog

from src.intelligence.grounded_ai import GroundedAI

logger = structlog.get_logger()


@dataclass
class SummaryResult:
    """Output of the summarization process."""
    text: str
    summary_type: str       # "extractive" or "abstractive"
    sentence_count: int
    source_language: str
    output_language: str


class Summarizer:
    """
    Dual-mode article summarizer.

    - Extractive: Free, local, uses TextRank (sumy). Best for cost efficiency.
    - Abstractive: Paid, uses Claude API. Best for quality + translation.
    """

    def __init__(self, enable_ai: bool = False, api_key: Optional[str] = None):
        self.enable_ai = enable_ai
        self.api_key = api_key
        self.ai = GroundedAI(enabled=enable_ai, api_key=api_key)

        # Lazy-load sumy components
        self._textrank = None
        self._tokenizer = None

    def _init_sumy(self):
        """Lazy-initialize sumy components."""
        if self._textrank is None:
            from sumy.parsers.plaintext import PlaintextParser
            from sumy.nlp.tokenizers import Tokenizer
            from sumy.summarizers.text_rank import TextRankSummarizer
            from sumy.nlp.stemmers import Stemmer

            self._parser_cls = PlaintextParser
            self._tokenizer_cls = Tokenizer
            self._textrank = TextRankSummarizer(Stemmer("english"))

    def summarize_extractive(
        self,
        text: str,
        language: str = "english",
        sentence_count: int = 3,
    ) -> SummaryResult:
        """
        Extract the most important sentences from the text.

        Uses TextRank algorithm — same family as Google's PageRank but
        applied to sentences. Free, fast, works offline.
        """
        if not text or len(text.strip()) < 50:
            return SummaryResult(
                text=text.strip(),
                summary_type="extractive",
                sentence_count=0,
                source_language=language,
                output_language=language,
            )

        self._init_sumy()

        # Map language codes to sumy-compatible names
        lang_map = {
            "en": "english", "mk": "english",  # sumy defaults
            "sq": "english", "de": "german",
            "fr": "french", "es": "spanish",
            "it": "italian", "pt": "portuguese",
        }
        sumy_lang = lang_map.get(language, "english")

        try:
            from sumy.parsers.plaintext import PlaintextParser
            from sumy.nlp.tokenizers import Tokenizer

            parser = PlaintextParser.from_string(text, Tokenizer(sumy_lang))
            sentences = self._textrank(parser.document, sentence_count)
            summary = " ".join(str(s) for s in sentences)

            return SummaryResult(
                text=summary,
                summary_type="extractive",
                sentence_count=len(sentences),
                source_language=language,
                output_language=language,
            )

        except Exception as e:
            logger.error("extractive_summary_failed", error=str(e))
            # Fallback: just take first N sentences
            return self._fallback_summary(text, sentence_count, language)

    def summarize_abstractive(
        self,
        text: str,
        source_language: str = "en",
        output_language: str = "en",
        sentence_count: int = 3,
        article_title: str = "",
    ) -> SummaryResult:
        """
        Generate a high-quality summary using Claude API.

        Can also translate: summarize a Macedonian article into English.
        """
        if not self.enable_ai:
            logger.warning("ai_summaries_disabled, falling_back_to_extractive")
            return self.summarize_extractive(text, source_language, sentence_count)

        try:
            lang_name = {
                "en": "English", "mk": "Macedonian", "sq": "Albanian",
                "de": "German", "fr": "French", "es": "Spanish",
            }.get(output_language, "English")
            generation = self.ai.summarize_article(
                title=article_title,
                text=text,
                output_language=lang_name,
                sentence_count=sentence_count,
            )
            if not generation.accepted:
                logger.warning("abstractive_summary_rejected", reason=generation.reason)
                return self.summarize_extractive(text, source_language, sentence_count)
            summary_text = re.sub(
                r"\s*\[S1\]\s*",
                " ",
                generation.payload["summary"],
            ).strip()

            return SummaryResult(
                text=summary_text,
                summary_type="abstractive",
                sentence_count=sentence_count,
                source_language=source_language,
                output_language=output_language,
            )

        except Exception as e:
            logger.error("abstractive_summary_failed", error=str(e))
            return self.summarize_extractive(text, source_language, sentence_count)

    def summarize(
        self,
        text: str,
        language: str = "en",
        sentence_count: int = 3,
        prefer_ai: bool = False,
        article_title: str = "",
        translate_to: Optional[str] = None,
    ) -> SummaryResult:
        """
        Main entry point — picks the best summarization strategy.

        - If prefer_ai=True and AI is enabled → abstractive
        - If translate_to is set → abstractive (needs AI for translation)
        - Otherwise → extractive (free)
        """
        needs_translation = translate_to and translate_to != language

        if (prefer_ai or needs_translation) and self.enable_ai:
            return self.summarize_abstractive(
                text=text,
                source_language=language,
                output_language=translate_to or language,
                sentence_count=sentence_count,
                article_title=article_title,
            )

        return self.summarize_extractive(text, language, sentence_count)

    @staticmethod
    def _fallback_summary(
        text: str, sentence_count: int, language: str
    ) -> SummaryResult:
        """Simple fallback: take the first N sentences."""
        sentences = []
        for sep in [". ", "! ", "? "]:
            if sep in text:
                parts = text.split(sep)
                sentences = [
                    p.strip() + sep.strip()
                    for p in parts[:sentence_count]
                    if p.strip()
                ]
                break

        if not sentences:
            # Just take first 300 chars
            sentences = [text[:300].strip() + "..."]

        return SummaryResult(
            text=" ".join(sentences),
            summary_type="extractive",
            sentence_count=len(sentences),
            source_language=language,
            output_language=language,
        )
