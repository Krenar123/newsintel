"""
Named Entity Recognition using spaCy — runs locally, zero API cost.

Extracts people, organizations, and locations from article text.
Handles deduplication, normalization, and context extraction.

Models used:
  - en_core_web_sm: English NER (fast, 12MB)
  - xx_ent_wiki_sm: Multilingual NER for non-English text
"""

import re
import unicodedata
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field

import yaml
import structlog

logger = structlog.get_logger()


def is_likely_entity_name(name: str, entity_type: str = "") -> bool:
    """Cheap read-side quality check for already stored entities."""
    canonical = EntityExtractor._canonicalize(name)
    entity_type = corrected_entity_type(name, entity_type)
    return not EntityExtractor.entity_quality_reasons(name, entity_type, canonical)


def corrected_entity_type(name: str, entity_type: str = "") -> str:
    """Return a corrected display/storage type for common NER mistakes."""
    canonical = EntityExtractor._canonicalize(name)
    folded = EntityExtractor._ascii_fold(canonical)
    if canonical == "\u0437\u0430\u043f\u0430\u0434\u0435\u043d \u0431\u0430\u043b\u043a\u0430\u043d":
        return "location"
    if folded in {"shkup", "tetove", "tetoves", "rusia", "shba"}:
        return "location"
    if canonical in EntityExtractor.ORGANIZATION_OVERRIDES:
        return "organization"
    if canonical in EntityExtractor.LOCATION_OVERRIDES:
        return "location"
    tokens = name.split()
    surname_suffixes = (
        "\u0441\u043a\u0438", "\u0441\u043a\u0430",
        "\u043e\u0432", "\u043e\u0432\u0430",
        "\u0435\u0432", "\u0435\u0432\u0430",
        "\u043e\u0441\u043a\u0438", "\u043e\u0441\u043a\u0430",
        "iqi", "i\u00e7i", "ski", "ska", "ov", "ova", "ev", "eva",
    )
    if (
        len(tokens) in (2, 3)
        and all(token[:1].isupper() for token in tokens)
        and tokens[-1].lower().endswith(surname_suffixes)
    ):
        return "person"
    return entity_type


@dataclass
class ExtractedEntity:
    """A single extracted entity with metadata."""
    name: str
    canonical_name: str         # Normalized for deduplication
    entity_type: str            # person, organization, location
    mention_count: int = 1
    context_snippets: list[str] = field(default_factory=list)
    confidence: float = 1.0


@dataclass
class EntityExtractionResult:
    """Full result of entity extraction from an article."""
    entities: list[ExtractedEntity]
    person_count: int = 0
    org_count: int = 0
    location_count: int = 0
    processing_time_ms: float = 0


@dataclass
class LexiconEntity:
    name: str
    canonical_name: str
    entity_type: str
    aliases: list[str] = field(default_factory=list)


class EntityExtractor:
    """
    Extracts named entities using spaCy NER models.

    Handles:
    - Multiple languages (English + multilingual fallback)
    - Deduplication (merging "Joe Biden" and "Biden")
    - Context extraction (the sentence where the entity appears)
    - Filtering out false positives (dates, common words, etc.)
    """

    # spaCy label → our entity type mapping
    LABEL_MAP = {
        "PERSON": "person",
        "PER": "person",          # multilingual model
        "ORG": "organization",
        "GPE": "location",        # Geo-Political Entity
        "LOC": "location",
        "FAC": "location",        # Facility
        "NORP": "organization",   # Nationalities/religious/political groups
        "EVENT": "event",
    }

    # Common false positives to filter out
    STOPWORDS = {
        "monday", "tuesday", "wednesday", "thursday", "friday",
        "saturday", "sunday", "january", "february", "march", "april",
        "may", "june", "july", "august", "september", "october",
        "november", "december", "reuters", "ap", "afp", "photo",
        "video", "update", "breaking", "exclusive", "image",
        "these", "they", "he", "she",
        "\u043e\u0432\u0438\u0435", "\u0442\u0438\u0435", "\u0442\u043e\u0458", "\u0442\u0430\u0430",
        "според", "уште", "наместо", "поврзани", "земјата", "денес",
        "вчера", "утре", "ова", "тоа", "кој", "која", "кои", "што",
        "затоа", "бидејќи", "сепак", "инаку", "најново", "фото",
        "видео", "извор", "вест", "вести", "објава", "соопштение",
        "последните", "изборниот законик последните",
        "суплементација затоа што", "слободен", "белата", "поени",
    }

    GENERIC_SINGLE_WORDS = {
        "влада", "владата", "министерство", "министерството",
        "собрание", "собранието", "партија", "партијата",
        "држава", "државата", "земја", "земјата", "јавноста",
        "опозиција", "опозицијата", "власт", "власта", "полиција",
        "полицијата", "суд", "судот", "обвинителство", "обвинителството",
        "претседател", "претседателот", "премиер", "премиерот",
        "министер", "министерот", "град", "градот",
        "делегација", "делегацијата", "делегации", "делегациите",
    }

    CONNECTOR_WORDS = {
        "и", "или", "но", "а", "во", "на", "со", "за", "од", "до",
        "кај", "кон", "по", "пред", "без", "меѓу", "што", "дека",
        "затоа", "бидејќи", "според", "ако", "кога", "како",
    }

    SOCIAL_SHARE_WORDS = {
        "facebook", "telegram", "viber", "whatsapp", "pinterest", "share", "x",
    }

    UI_FRAGMENT_WORDS = {
        "lexo", "spotify", "transmeton", "arrestuan", "region", "tete", "tetes",
        "veriut", "football", "fudbal",
    }

    SUSPICIOUS_PHRASE_PATTERNS = [
        re.compile(pattern, re.IGNORECASE) for pattern in [
            r"\b(according|instead|because|after|before|latest)\b",
            r"\b(u\s+arrestuan|telegram\s+pinterest|telegram\s+viber|facebook\s+x\s+whatsapp)\b",
            r"(\u0440\u0435\u0433\u0438\u043e\u043d|\u0444\u0443\u0434\u0431\u0430\u043b|\u0440\u0435\u0430\u0433\u0438\u0440)",
            r"(\u0430\u043b\u0431\u0430\u043d\u0438\u0458\u0430[-\s]+\u0435\u0443)",
            r"(\u0441\u043f\u043e\u0440\u0435\u0434|\u043d\u0430\u043c\u0435\u0441\u0442\u043e|\u0437\u0430\u0442\u043e\u0430|\u043f\u043e\u0441\u043b\u0435\u0434\u043d\u0438\u0442\u0435|\u043f\u0440\u0435\u0434|\u043e\u0442\u043a\u0430\u043a\u043e)",
            r"(\u0437\u0430\u0442\u043e\u0430\s+\u0448\u0442\u043e|\u0438\u0437\u0431\u043e\u0440\u043d\u0438\u043e\u0442\s+\u0437\u0430\u043a\u043e\u043d\u0438\u043a)",
        ]
    ]

    LOCATION_OVERRIDES = {
        "македонија", "северна македонија", "грција", "бугарија",
        "албанија", "србија", "косово", "иран", "русија", "сад",
        "европа", "вашингтон", "скопје", "брисел", "софија",
        "белград", "приштина", "тирана", "атина", "техеран",
        "рим", "охрид", "хавана",
        "macedonia", "north macedonia", "greece", "bulgaria",
        "albania", "serbia", "kosovo", "iran", "russia", "usa",
        "washington", "skopje", "brussels",
    }

    ORGANIZATION_OVERRIDES = {
        "европската унија", "европска унија", "еу", "нато", "он",
        "обединети нации", "вмро дпмне", "сдсм", "дуи", "левица",
        "знам", "алијанса за албанците", "вреди",
        "european union", "eu", "nato", "un",
    }

    def __init__(self, languages: list[str] = None):
        self._nlp_models = {}
        self._languages = languages or ["en"]
        self._lexicon = self._load_lexicon()
        self._load_models()

    def _load_lexicon(self) -> list[LexiconEntity]:
        """Load curated known entities for the pilot market."""
        path = Path(__file__).resolve().parents[2] / "config" / "entities" / "north_macedonia.yaml"
        if not path.exists():
            return []
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        entities = []
        for item in data.get("entities", []):
            name = str(item.get("name", "")).strip()
            entity_type = str(item.get("type", "")).strip()
            if not name or entity_type not in {"person", "organization", "location"}:
                continue
            aliases = [str(alias).strip() for alias in item.get("aliases", []) if str(alias).strip()]
            entities.append(LexiconEntity(
                name=name,
                canonical_name=self._canonicalize(name),
                entity_type=entity_type,
                aliases=aliases,
            ))
        logger.info("loaded_entity_lexicon", count=len(entities), path=str(path))
        return entities

    def _load_models(self):
        """Load spaCy models for configured languages."""
        import spacy

        # Always try English model
        try:
            self._nlp_models["en"] = spacy.load("en_core_web_sm")
            logger.info("loaded_spacy_model", model="en_core_web_sm")
        except OSError:
            logger.warning("spacy_model_not_found", model="en_core_web_sm")

        # Try multilingual model for non-English
        non_en = [l for l in self._languages if l != "en"]
        if non_en:
            try:
                self._nlp_models["xx"] = spacy.load("xx_ent_wiki_sm")
                logger.info("loaded_spacy_model", model="xx_ent_wiki_sm")
            except OSError:
                logger.warning("spacy_model_not_found", model="xx_ent_wiki_sm")

    def extract(
        self,
        text: str,
        language: str = "en",
        max_entities: int = 50,
    ) -> EntityExtractionResult:
        """
        Extract named entities from article text.

        Args:
            text:           Article content (plain text)
            language:       ISO language code
            max_entities:   Maximum entities to return

        Returns:
            EntityExtractionResult with deduplicated entities
        """
        import time
        start = time.time()

        if not text or len(text.strip()) < 20:
            return EntityExtractionResult(entities=[])

        # Pick the right model
        nlp = self._get_model(language)
        if nlp is None:
            logger.warning("no_ner_model_available", language=language)
            return EntityExtractionResult(entities=[])

        # Process text (cap at 100k chars for performance)
        doc = nlp(text[:100_000])

        # Collect raw entities
        raw_entities: dict[str, dict] = self._extract_lexicon_entities(text[:100_000])
        sentences = list(doc.sents)

        for ent in doc.ents:
            # Map spaCy label to our type
            entity_type = self.LABEL_MAP.get(ent.label_)
            if not entity_type:
                continue

            name = ent.text.strip()

            canonical = self._canonicalize(name)
            entity_type = self._correct_entity_type(canonical, entity_type)

            # Filter garbage
            if not self._is_valid_entity(name, entity_type, canonical):
                continue
            if self._is_covered_by_lexicon(canonical, entity_type, raw_entities):
                continue

            if canonical not in raw_entities:
                raw_entities[canonical] = {
                    "name": name,
                    "canonical_name": canonical,
                    "entity_type": entity_type,
                    "count": 0,
                    "contexts": [],
                }

            raw_entities[canonical]["count"] += 1

            # Extract context sentence
            context = self._get_context(ent, sentences)
            if context and len(raw_entities[canonical]["contexts"]) < 3:
                raw_entities[canonical]["contexts"].append(context)

        # Merge similar entities (e.g., "Biden" and "Joe Biden")
        merged = self._merge_similar(raw_entities)

        # Sort by mention count, take top N
        sorted_entities = sorted(
            merged.values(), key=lambda e: e["count"], reverse=True
        )[:max_entities]

        # Build result
        entities = [
            ExtractedEntity(
                name=e["name"],
                canonical_name=e["canonical_name"],
                entity_type=e["entity_type"],
                mention_count=e["count"],
                context_snippets=e["contexts"],
            )
            for e in sorted_entities
        ]

        elapsed_ms = (time.time() - start) * 1000

        return EntityExtractionResult(
            entities=entities,
            person_count=sum(1 for e in entities if e.entity_type == "person"),
            org_count=sum(
                1 for e in entities if e.entity_type == "organization"
            ),
            location_count=sum(
                1 for e in entities if e.entity_type == "location"
            ),
            processing_time_ms=round(elapsed_ms, 1),
        )

    def _get_model(self, language: str):
        """Get the appropriate spaCy model for the language."""
        if language == "en" and "en" in self._nlp_models:
            return self._nlp_models["en"]
        if "xx" in self._nlp_models:
            return self._nlp_models["xx"]
        if "en" in self._nlp_models:
            return self._nlp_models["en"]  # fallback
        return None

    def _extract_lexicon_entities(self, text: str) -> dict[str, dict]:
        """Extract curated entities and normalize aliases before ML NER results."""
        raw_entities: dict[str, dict] = {}
        if not text or not self._lexicon:
            return raw_entities

        sentence_texts = self._split_sentences(text)
        for item in self._lexicon:
            names = [item.name, *item.aliases]
            contexts: list[str] = []
            spans: list[tuple[int, int]] = []
            for alias in sorted(names, key=len, reverse=True):
                pattern = re.compile(rf"(?<!\w){re.escape(alias)}(?!\w)", re.IGNORECASE)
                for match in pattern.finditer(text):
                    span = (match.start(), match.end())
                    if any(span[0] < end and span[1] > start for start, end in spans):
                        continue
                    spans.append(span)
                    context = self._context_for_span(match.start(), match.end(), sentence_texts)
                    if context and context not in contexts:
                        contexts.append(context)

            if spans:
                raw_entities[item.canonical_name] = {
                    "name": item.name,
                    "canonical_name": item.canonical_name,
                    "entity_type": item.entity_type,
                    "count": len(spans),
                    "contexts": contexts[:3],
                    "lexicon": True,
                    "matched_names": {
                        self._canonicalize(value) for value in names
                    },
                }
        return raw_entities

    @staticmethod
    def _is_covered_by_lexicon(
        canonical: str,
        entity_type: str,
        raw_entities: dict[str, dict],
    ) -> bool:
        for existing_canonical, existing in raw_entities.items():
            if not existing.get("lexicon"):
                continue
            matched_names = existing.get("matched_names") or {existing_canonical}
            for matched_name in matched_names:
                if canonical == matched_name:
                    return True
                # Suppress partial or expanded ML spans already represented by a
                # curated entity, even when the ML model assigned the wrong type.
                if min(len(canonical), len(matched_name)) >= 4 and (
                    canonical in matched_name or matched_name in canonical
                ):
                    return True
        return False

    @staticmethod
    def _split_sentences(text: str) -> list[str]:
        return [
            part.strip()
            for part in re.split(r"(?<=[.!?।])\s+|\n+", text)
            if part.strip()
        ]

    @staticmethod
    def _context_for_span(start: int, end: int, sentences: list[str]) -> Optional[str]:
        cursor = 0
        for sentence in sentences:
            sentence_start = cursor
            sentence_end = cursor + len(sentence)
            if start >= sentence_start and end <= sentence_end:
                return sentence[:300] + ("..." if len(sentence) > 300 else "")
            cursor = sentence_end + 1
        return None

    def _is_valid_entity(
        self,
        name: str,
        entity_type: str,
        canonical: Optional[str] = None,
    ) -> bool:
        """Filter out false positive entities."""
        canonical = canonical or self._canonicalize(name)
        return self._is_valid_entity_name(name, entity_type, canonical)

    @classmethod
    def _is_valid_entity_name(
        cls,
        name: str,
        entity_type: str,
        canonical: str,
    ) -> bool:
        return not cls.entity_quality_reasons(name, entity_type, canonical)

    @classmethod
    def entity_quality_reasons(
        cls,
        name: str,
        entity_type: str,
        canonical: Optional[str] = None,
    ) -> list[str]:
        """Return explainable reasons an entity candidate looks noisy."""
        canonical = canonical or cls._canonicalize(name)
        entity_type = corrected_entity_type(name, entity_type)
        tokens = canonical.split()
        folded = cls._ascii_fold(canonical)
        folded_tokens = set(folded.split())
        reasons: list[str] = []

        if len(name) < 2 or len(name) > 100:
            reasons.append("invalid_length")
        if re.match(r'^[\d\s\-/.,]+$', name):
            reasons.append("numeric_or_date_like")
        if canonical in cls.STOPWORDS:
            reasons.append("stopword")
        if canonical in {
            "\u0443\u043f\u0440\u0430\u0432\u0430",
            "\u0443\u043f\u0440\u0430\u0432\u0430\u0442\u0430",
        }:
            reasons.append("generic_word")
        if tokens and sum(1 for token in tokens if token in cls.CONNECTOR_WORDS) >= max(1, len(tokens) // 2):
            reasons.append("connector_heavy")

        stripped = name.strip()
        has_upper = any(ch.isupper() for ch in stripped)
        is_domain = "." in stripped and any(ch.isalpha() for ch in stripped)
        is_acronym = stripped.upper() == stripped and any(ch.isalpha() for ch in stripped)
        if not has_upper and not is_domain and not is_acronym:
            reasons.append("not_capitalized")
        if is_domain and canonical not in cls.ORGANIZATION_OVERRIDES:
            reasons.append("domain_like")

        if len(tokens) == 1 and canonical in cls.GENERIC_SINGLE_WORDS:
            reasons.append("generic_single_word")

        if any(pattern.search(canonical) for pattern in cls.SUSPICIOUS_PHRASE_PATTERNS):
            reasons.append("phrase_fragment")
        if len(folded_tokens & cls.SOCIAL_SHARE_WORDS) >= 2:
            reasons.append("social_share_widget")
        if folded in cls.UI_FRAGMENT_WORDS or folded_tokens & cls.UI_FRAGMENT_WORDS:
            reasons.append("ui_fragment")
        if re.search(r"\b\d{1,2}[./-]\d{1,2}[./-]\d{2,4}\b", name) and any(ch.isalpha() for ch in name):
            reasons.append("date_fragment")
        if re.fullmatch(r"(?:[A-Z]\.\s*){2,4}", name.strip()):
            reasons.append("initials_fragment")

        if entity_type == "person":
            if len(name.split()) == 1 and len(name) < 4:
                reasons.append("person_too_short")
            if len(tokens) > 4:
                reasons.append("person_too_long")
            if any(token in cls.CONNECTOR_WORDS for token in tokens):
                reasons.append("person_has_connector")
            if len(tokens) == 1 and canonical in cls.GENERIC_SINGLE_WORDS:
                reasons.append("person_generic_single_word")

        return sorted(set(reasons))

    def _correct_entity_type(self, canonical: str, entity_type: str) -> str:
        """Fix common multilingual NER label mistakes before storage."""
        if canonical in self.ORGANIZATION_OVERRIDES:
            return "organization"
        if canonical in self.LOCATION_OVERRIDES:
            return "location"
        return entity_type

    @staticmethod
    def _canonicalize(name: str) -> str:
        """Normalize entity name for deduplication."""
        # Lowercase, strip extra whitespace
        canonical = " ".join(name.lower().split())
        # Remove common suffixes/prefixes
        canonical = re.sub(r'\b(mr|mrs|ms|dr|prof|sr|jr)\b\.?\s*', '', canonical)
        return canonical.strip()

    @staticmethod
    def _ascii_fold(value: str) -> str:
        """Lowercase and remove accents/punctuation for multilingual quality rules."""
        normalized = unicodedata.normalize("NFKD", value)
        ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
        ascii_value = re.sub(r"[^a-z0-9]+", " ", ascii_value.lower())
        return " ".join(ascii_value.split())

    @staticmethod
    def _get_context(ent, sentences) -> Optional[str]:
        """Get the sentence containing the entity."""
        for sent in sentences:
            if ent.start >= sent.start and ent.end <= sent.end:
                context = sent.text.strip()
                # Cap length
                if len(context) > 300:
                    context = context[:300] + "..."
                return context
        return None

    @staticmethod
    def _merge_similar(entities: dict[str, dict]) -> dict[str, dict]:
        """
        Merge entities that are likely the same
        (e.g., 'Biden' and 'Joe Biden').
        """
        keys = sorted(entities.keys(), key=len, reverse=True)
        merged_into: dict[str, str] = {}  # short_key → long_key

        for i, long_key in enumerate(keys):
            for short_key in keys[i + 1:]:
                if short_key in merged_into:
                    continue

                # Check if short name is a substring of long name
                # and they share the same entity type
                long_ent = entities[long_key]
                short_ent = entities[short_key]

                if long_ent["entity_type"] != short_ent["entity_type"]:
                    continue

                if short_key in long_key:
                    # Merge short into long
                    long_ent["count"] += short_ent["count"]
                    long_ent["contexts"].extend(short_ent["contexts"])
                    long_ent["contexts"] = long_ent["contexts"][:3]
                    merged_into[short_key] = long_key

        # Remove merged entities
        for key in merged_into:
            entities.pop(key, None)

        return entities
