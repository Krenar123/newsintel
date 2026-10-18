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

import structlog

from config import settings
from src.processing.entity_registry import EntityRegistry, canonicalize

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
    confidence: float = 0.55
    provenance: list[str] = field(default_factory=lambda: ["spacy_ner"])
    publishable: bool = False
    matched_aliases: list[str] = field(default_factory=list)
    decision_reasons: list[str] = field(default_factory=list)
    evidence_count: int = 1


@dataclass
class EntityExtractionResult:
    """Full result of entity extraction from an article."""
    entities: list[ExtractedEntity]
    person_count: int = 0
    org_count: int = 0
    location_count: int = 0
    processing_time_ms: float = 0


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
        "служба", "службата", "компанија", "компанијата",
        "надлежните", "автобус", "автобусот", "почетната",
    }

    PERSON_SURNAME_SUFFIXES = (
        "ски", "ска", "ов", "ова", "ев", "ева", "оски", "оска",
        "иќ", "ić", "iqi", "içi",
    )
    PERSON_CONTEXT_RE = re.compile(
        r"\b(премиер|претседател|министер|директор|градоначалник|пратеник|"
        r"лидер|професор|доктор|рече|изјави|соопшти|најави|обвини|побара|"
        r"kryeminist(?:ri|re)?|president(?:i|ja)?|minist(?:ri|re)?|tha|deklaroi|"
        r"prime minister|president|minister|director|said|stated)\b",
        re.IGNORECASE,
    )
    ORGANIZATION_CONTEXT_RE = re.compile(
        r"\b(парти(?:ја|јата)|коалици(?:ја|јата)|министерство|агенци(?:ја|јата)|"
        r"комиси(?:ја|јата)|служб(?:а|ата)|компани(?:ја|јата)|банка|универзитет|"
        r"телевизи(?:ја|јата)|портал|здружение|организаци(?:ја|јата)|"
        r"parti(?:a|ja)?|koalicion|ministri|agjenci|komision|kompani|bank|"
        r"party|coalition|ministry|agency|commission|company|bank|university)\b",
        re.IGNORECASE,
    )
    LOCATION_CONTEXT_RE = re.compile(
        r"\b(во|од|до|кон|низ|кај|преку|село(?:то)?|град(?:от)?|општин(?:а|ата)|"
        r"në|nga|drejt|qytet(?:i)?|fshat(?:i)?|in|from|to|city|village)\b",
        re.IGNORECASE,
    )

    CONNECTOR_WORDS = {
        "и", "или", "но", "а", "во", "на", "со", "за", "од", "до",
        "кај", "кон", "по", "пред", "без", "меѓу", "преку", "што", "дека",
        "затоа", "бидејќи", "според", "ако", "кога", "како",
    }

    SOCIAL_SHARE_WORDS = {
        "facebook", "telegram", "viber", "whatsapp", "pinterest", "share", "tweet", "x",
    }

    MODEL_LEADING_NOISE = {
        "победи", "следете", "прочитајте", "видете", "сподели",
        "share", "tweet", "watch", "read",
    }

    UI_FRAGMENT_WORDS = {
        "lexo", "spotify", "transmeton", "arrestuan", "region", "tete", "tetes",
        "veriut", "football", "fudbal",
    }

    # Exact, observed legacy false positives. These are intentionally narrower
    # than the general quality rules because the migration may hide them without
    # human review; all other model discoveries are only queued for review.
    EXPLICIT_NOISE_NAMES = {
        "një", "sipas", "çfarë", "burimi", "portali", "ndërkohë",
        "etiketat", "këto", "shënim", "dërgoni", "gjithashtu", "ndërsa",
        "nëse", "edhe", "ligjin", "vendimi", "shtetit", "është", "kështu",
        "kryetari", "агенцијата", "центарот", "водата", "следете", "законот",
        "иако", "flaka dossier epstein", "flaka media",
        "flaka flaka", "redaksia flaka flaka ai", "media sociale",
        "ai media sociale",
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

    def _load_lexicon(self) -> list:
        """Load and validate the curated entity registry."""
        path = Path(__file__).resolve().parents[2] / "config" / "entities" / "north_macedonia.yaml"
        self._registry = EntityRegistry.load(path)
        logger.info(
            "loaded_entity_lexicon",
            count=len(self._registry.entities),
            issues=len(self._registry.issues),
            path=str(path),
        )
        return list(self._registry.entities)

    def _load_models(self):
        """Load local entity candidate models configured for this worker."""
        import spacy

        self._gliner = None

        # Always try English model
        try:
            self._nlp_models["en"] = self._ensure_sentence_boundaries(
                spacy.load("en_core_web_sm")
            )
            logger.info("loaded_spacy_model", model="en_core_web_sm")
        except OSError:
            logger.warning("spacy_model_not_found", model="en_core_web_sm")

        # Try multilingual model for non-English
        non_en = [l for l in self._languages if l != "en"]
        if non_en:
            try:
                self._nlp_models["xx"] = self._ensure_sentence_boundaries(
                    spacy.load("xx_ent_wiki_sm")
                )
                logger.info("loaded_spacy_model", model="xx_ent_wiki_sm")
            except OSError:
                logger.warning("spacy_model_not_found", model="xx_ent_wiki_sm")

        if settings.enable_gliner_ner:
            try:
                from gliner import GLiNER
                self._gliner = GLiNER.from_pretrained(settings.gliner_model)
                logger.info("loaded_gliner_model", model=settings.gliner_model)
            except ImportError:
                logger.error(
                    "gliner_not_installed",
                    hint="Install requirements-ner.txt before enabling GLiNER",
                )
            except Exception as exc:
                logger.error("gliner_model_load_failed", model=settings.gliner_model, error=str(exc))

    @staticmethod
    def _ensure_sentence_boundaries(nlp):
        """Add a lightweight sentence segmenter when a model provides none."""
        if not {"parser", "senter", "sentencizer"}.intersection(nlp.pipe_names):
            nlp.add_pipe("sentencizer")
        return nlp

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
            logger.warning("no_ner_model_available_using_registry", language=language)

        # Trusted registry extraction must continue even when an ML model is absent.
        limited_text = text[:100_000]
        raw_entities: dict[tuple[str, str], dict] = self._extract_lexicon_entities(
            limited_text, language=language
        )
        doc = nlp(limited_text) if nlp is not None else None
        sentences = list(doc.sents) if doc is not None else []

        for ent in doc.ents if doc is not None else []:
            # Map spaCy label to our type
            entity_type = self.LABEL_MAP.get(ent.label_)
            if not entity_type:
                continue

            name = ent.text.strip()
            context = self._get_context(ent, sentences)

            canonical = self._canonicalize(name)
            entity_type = self._correct_entity_type(canonical, entity_type)
            entity_type = self._contextual_entity_type(name, entity_type, context)

            # Filter garbage
            if not self._is_valid_entity(name, entity_type, canonical):
                continue
            if self._is_covered_by_lexicon(canonical, entity_type, raw_entities):
                continue

            identity = (canonical, entity_type)
            if identity not in raw_entities:
                raw_entities[identity] = {
                    "name": name,
                    "canonical_name": canonical,
                    "entity_type": entity_type,
                    "count": 0,
                    "contexts": [],
                    "confidence": 0.0,
                    "provenance": {"spacy_ner"},
                    "publishable": False,
                    "matched_aliases": set(),
                    "decision_reasons": {"model_discovery_requires_review"},
                    "model_votes": {"spacy_ner"},
                    "model_score": 0.55,
                    "spans": set(),
                }

            raw_entities[identity].setdefault("model_votes", set()).add("spacy_ner")
            raw_entities[identity].setdefault("provenance", set()).add("spacy_ner")
            raw_entities[identity].setdefault("spans", set()).add(
                (int(ent.start_char), int(ent.end_char))
            )
            raw_entities[identity]["count"] = len(raw_entities[identity]["spans"])

            # Preserve evidence for review and sentiment.
            if context and len(raw_entities[identity]["contexts"]) < 3:
                raw_entities[identity]["contexts"].append(context)

        self._extract_gliner_entities(limited_text, language, raw_entities)

        # Curated aliases resolve identity; unreviewed candidates remain separate.
        merged = self._merge_similar(raw_entities)
        admitted = []
        for candidate in merged.values():
            if not self._candidate_should_keep(candidate):
                continue
            if not candidate.get("lexicon"):
                candidate.setdefault("decision_reasons", set()).add(
                    "candidate_context_supported"
                )
            admitted.append(candidate)
        admitted = self._resolve_type_conflicts(admitted)

        # Sort by mention count and review priority, then take the article cap.
        sorted_entities = sorted(
            admitted,
            key=lambda item: (item["count"], self._candidate_confidence(item)),
            reverse=True,
        )[:max_entities]

        # Build result
        entities = [
            ExtractedEntity(
                name=e["name"],
                canonical_name=e["canonical_name"],
                entity_type=e["entity_type"],
                mention_count=e["count"],
                context_snippets=e["contexts"],
                confidence=self._candidate_confidence(e),
                provenance=sorted(e.get("provenance") or {"spacy_ner"}),
                publishable=bool(e.get("publishable", False)),
                matched_aliases=sorted(e.get("matched_aliases") or []),
                decision_reasons=sorted(e.get("decision_reasons") or []),
                evidence_count=int(e.get("count", 1)),
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

    def _extract_lexicon_entities(
        self, text: str, *, language: str = ""
    ) -> dict[tuple[str, str], dict]:
        """Extract trusted aliases through the validated country registry."""
        raw_entities: dict[tuple[str, str], dict] = {}
        if not text or not self._lexicon:
            return raw_entities

        registry = getattr(self, "_registry", None)
        if registry is None:
            return raw_entities
        for match in registry.match(text, language=language):
            key = (match.entity.canonical_name, match.entity.entity_type)
            item = raw_entities.setdefault(key, {
                "name": match.entity.name,
                "canonical_name": match.entity.canonical_name,
                "entity_type": match.entity.entity_type,
                "count": 0,
                "contexts": [],
                "lexicon": True,
                "confidence": 1.0,
                "provenance": {"curated_lexicon"},
                "publishable": False,
                "matched_aliases": set(),
                "matched_names": {
                    self._canonicalize(alias.value) for alias in match.entity.aliases
                },
                "decision_reasons": {"validated_registry_alias"},
                "model_votes": {"curated_lexicon"},
                "model_score": 1.0,
                "spans": set(),
            })
            item["spans"].add((match.start, match.end))
            item["count"] = len(item["spans"])
            item["matched_aliases"].add(match.alias.value)
            item["publishable"] = bool(item["publishable"] or match.alias.publishable)
            context = registry.context_for_span(text, match.start, match.end)
            if context and context not in item["contexts"] and len(item["contexts"]) < 3:
                item["contexts"].append(context)
        return raw_entities

    def _extract_gliner_entities(
        self,
        text: str,
        language: str,
        raw_entities: dict[tuple[str, str], dict],
    ) -> None:
        """Add review-only multilingual transformer candidates to the ensemble."""
        model = getattr(self, "_gliner", None)
        if model is None:
            return
        labels = ["person", "organization", "location"]
        limited = text[: max(500, int(settings.gliner_max_chars))]
        for chunk, offset in self._iter_model_chunks(limited):
            try:
                predictions = model.predict_entities(
                    chunk,
                    labels,
                    threshold=float(settings.gliner_threshold),
                )
            except Exception as exc:
                logger.warning("gliner_prediction_failed", error=str(exc))
                return
            for prediction in predictions:
                entity_type = str(prediction.get("label", "")).casefold()
                if entity_type not in labels:
                    continue
                name = str(prediction.get("text", "")).strip()
                start = int(prediction.get("start", 0)) + offset
                end = int(prediction.get("end", start + len(name))) + offset
                context = EntityRegistry.context_for_span(limited, start, end)
                canonical = self._canonicalize(name)
                entity_type = self._correct_entity_type(canonical, entity_type)
                entity_type = self._contextual_entity_type(name, entity_type, context)
                if not self._is_valid_entity(name, entity_type, canonical):
                    continue
                if self._is_covered_by_lexicon(canonical, entity_type, raw_entities):
                    continue
                identity = (canonical, entity_type)
                candidate = raw_entities.setdefault(identity, {
                    "name": name,
                    "canonical_name": canonical,
                    "entity_type": entity_type,
                    "count": 0,
                    "contexts": [],
                    "confidence": 0.0,
                    "provenance": set(),
                    "publishable": False,
                    "matched_aliases": set(),
                    "decision_reasons": {"model_discovery_requires_review"},
                    "model_votes": set(),
                    "model_score": 0.0,
                    "spans": set(),
                })
                candidate.setdefault("spans", set()).add((start, end))
                candidate["count"] = len(candidate["spans"])
                candidate.setdefault("provenance", set()).add("gliner_multilingual")
                candidate.setdefault("model_votes", set()).add("gliner_multilingual")
                candidate["model_score"] = max(
                    float(candidate.get("model_score") or 0.0),
                    float(prediction.get("score") or 0.0),
                )
                if len(candidate["model_votes"]) >= 2:
                    candidate.setdefault("decision_reasons", set()).add("multi_model_agreement")
                if context and context not in candidate["contexts"] and len(candidate["contexts"]) < 3:
                    candidate["contexts"].append(context)

    @staticmethod
    def _iter_model_chunks(text: str, target_size: int = 4000):
        cursor = 0
        while cursor < len(text):
            end = min(cursor + target_size, len(text))
            if end < len(text):
                boundary = max(
                    text.rfind("\n", cursor + target_size // 2, end),
                    text.rfind(".", cursor + target_size // 2, end),
                )
                if boundary > cursor:
                    end = boundary + 1
            yield text[cursor:end], cursor
            cursor = end

    @classmethod
    def _candidate_should_keep(cls, candidate: dict) -> bool:
        """Reject low-information model output before it reaches the review DB."""
        if candidate.get("lexicon"):
            return True
        votes = set(candidate.get("model_votes") or [])
        score = float(candidate.get("model_score") or 0.0)
        if len(votes) >= 2 or ("gliner_multilingual" in votes and score >= 0.80):
            return True
        if int(candidate.get("count", 0)) >= 2:
            return True

        name = str(candidate.get("name", "")).strip()
        tokens = [token for token in re.findall(r"[^\W_]+", name, re.UNICODE) if token]
        context = " ".join(candidate.get("contexts") or [])
        entity_type = str(candidate.get("entity_type", ""))
        if not tokens:
            return False

        if tokens[0].casefold() in cls.MODEL_LEADING_NOISE:
            return False
        if folded_tokens := {token.casefold() for token in tokens}:
            if folded_tokens <= cls.SOCIAL_SHARE_WORDS:
                return False

        if entity_type == "person":
            if len(tokens) >= 2:
                allowed_particles = {"de", "del", "der", "van", "von", "bin", "al"}
                return (
                    tokens[0].casefold() not in cls.CONNECTOR_WORDS
                    and all(
                        token[:1].isupper() or token.casefold() in allowed_particles
                        for token in tokens
                    )
                )
            folded = tokens[0].casefold()
            return (
                folded.endswith(cls.PERSON_SURNAME_SUFFIXES)
                or cls._cue_before_name(name, context, cls.PERSON_CONTEXT_RE)
                or cls._cue_after_name(name, context, cls.PERSON_CONTEXT_RE)
            )

        if entity_type == "organization":
            is_acronym = name.upper() == name and 2 <= len("".join(tokens)) <= 12
            return (
                is_acronym
                or cls._cue_before_name(name, context, cls.ORGANIZATION_CONTEXT_RE)
                or cls._cue_after_name(name, context, cls.ORGANIZATION_CONTEXT_RE)
            )

        if entity_type == "location":
            if (
                len(tokens) == 1
                and tokens[0].casefold().endswith("ите")
                and not ("gliner_multilingual" in votes and score >= 0.80)
            ):
                return False
            if len(tokens) == 1 and re.search(
                rf"(?i)(?<!\w){re.escape(name)}\s+(село|град|област|регион)\b",
                context,
            ):
                return False
            return cls._cue_before_name(name, context, cls.LOCATION_CONTEXT_RE)

        return False

    @staticmethod
    def _name_matches(name: str, context: str):
        return re.finditer(rf"(?<!\w){re.escape(name)}(?!\w)", context, re.IGNORECASE)

    @classmethod
    def _cue_before_name(cls, name: str, context: str, cue_pattern) -> bool:
        for name_match in cls._name_matches(name, context or ""):
            before = context[max(0, name_match.start() - 80):name_match.start()]
            cues = list(cue_pattern.finditer(before))
            if cues and len(re.findall(r"[^\W_]+", before[cues[-1].end():], re.UNICODE)) <= 2:
                return True
        return False

    @classmethod
    def _cue_after_name(cls, name: str, context: str, cue_pattern) -> bool:
        for name_match in cls._name_matches(name, context or ""):
            after = context[name_match.end():min(len(context), name_match.end() + 80)]
            cue = cue_pattern.search(after)
            if cue and len(re.findall(r"[^\W_]+", after[:cue.start()], re.UNICODE)) <= 2:
                return True
        return False

    @classmethod
    def _contextual_entity_type(
        cls,
        name: str,
        entity_type: str,
        context: Optional[str],
    ) -> str:
        """Correct model labels only when a nearby linguistic cue supports it."""
        context = context or ""
        if (
            cls._cue_before_name(name, context, cls.ORGANIZATION_CONTEXT_RE)
            or cls._cue_after_name(name, context, cls.ORGANIZATION_CONTEXT_RE)
        ):
            return "organization"
        if cls._cue_before_name(name, context, cls.LOCATION_CONTEXT_RE):
            return "location"
        return entity_type

    @classmethod
    def _resolve_type_conflicts(cls, candidates: list[dict]) -> list[dict]:
        grouped: dict[str, list[dict]] = {}
        for candidate in candidates:
            grouped.setdefault(str(candidate.get("canonical_name", "")), []).append(candidate)
        resolved = []
        for variants in grouped.values():
            if len(variants) == 1:
                resolved.extend(variants)
                continue
            winner = max(variants, key=cls._type_resolution_rank)
            winner.setdefault("decision_reasons", set()).add("type_conflict_resolved")
            resolved.append(winner)
        return resolved

    @classmethod
    def _type_resolution_rank(cls, candidate: dict) -> tuple:
        if candidate.get("lexicon"):
            return (100, 1.0)
        name = str(candidate.get("name", ""))
        kind = str(candidate.get("entity_type", ""))
        context = " ".join(candidate.get("contexts") or [])
        tokens = re.findall(r"[^\W_]+", name, re.UNICODE)
        score = 0
        if kind == "location" and cls._cue_before_name(name, context, cls.LOCATION_CONTEXT_RE):
            score += 30
        if kind == "organization" and (
            cls._cue_before_name(name, context, cls.ORGANIZATION_CONTEXT_RE)
            or cls._cue_after_name(name, context, cls.ORGANIZATION_CONTEXT_RE)
        ):
            score += 30
        if kind == "person" and len(tokens) >= 2 and all(token[:1].isupper() for token in tokens):
            score += 20
        surname_shaped = bool(
            tokens and tokens[-1].casefold().endswith(cls.PERSON_SURNAME_SUFFIXES)
        )
        if kind == "person" and surname_shaped:
            score += 15
        if kind == "person" and (
            cls._cue_before_name(name, context, cls.PERSON_CONTEXT_RE)
            or cls._cue_after_name(name, context, cls.PERSON_CONTEXT_RE)
        ):
            score += 30
        if kind == "location" and surname_shaped:
            score -= 20
        if kind == "organization" and name.upper() == name and any(ch.isalpha() for ch in name):
            score += 20
        return (score, cls._candidate_confidence(candidate))

    @staticmethod
    def _candidate_confidence(candidate: dict) -> float:
        """Produce an explainable ranking score, never an approval decision."""
        if candidate.get("lexicon"):
            return 1.0
        name = str(candidate.get("name", ""))
        tokens = name.split()
        score = max(0.35, float(candidate.get("model_score") or 0.0))
        score += 0.08 if len(tokens) >= 2 else 0.0
        score += 0.06 if int(candidate.get("count", 0)) >= 2 else 0.0
        score += 0.04 if name[:1].isupper() else 0.0
        score += 0.10 if len(candidate.get("model_votes") or []) >= 2 else 0.0
        return round(min(score, 0.95), 3)

    @classmethod
    def is_explicit_noise(cls, name: str) -> bool:
        """Return true only for exact false positives safe to hide automatically."""
        return cls._canonicalize(name) in cls.EXPLICIT_NOISE_NAMES

    @staticmethod
    def _is_covered_by_lexicon(
        canonical: str,
        entity_type: str,
        raw_entities: dict[tuple[str, str], dict],
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
        if canonical in cls.EXPLICIT_NOISE_NAMES:
            reasons.append("explicit_noise")
        if tokens and all(token in cls.EXPLICIT_NOISE_NAMES for token in tokens):
            reasons.append("explicit_noise_phrase")
        if canonical in {
            "\u0443\u043f\u0440\u0430\u0432\u0430",
            "\u0443\u043f\u0440\u0430\u0432\u0430\u0442\u0430",
        }:
            reasons.append("generic_word")
        connector_count = sum(1 for token in tokens if token in cls.CONNECTOR_WORDS)
        if connector_count >= 2 and connector_count * 2 >= len(tokens):
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
        if (
            len(folded_tokens & cls.SOCIAL_SHARE_WORDS) >= 2
            or (folded_tokens and folded_tokens <= cls.SOCIAL_SHARE_WORDS)
        ):
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
        return canonicalize(name)

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
    def _merge_similar(entities: dict) -> dict:
        """Keep candidates separate unless the curated registry resolved them.

        Substring merging is unsafe for shared surnames and names embedded in
        organizations. Duplicate suggestions belong in review, not extraction.
        """
        return entities
