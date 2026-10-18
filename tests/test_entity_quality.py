import spacy
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.models.database import Entity, EntityStatus, EntityType
from src.processing.entities import EntityExtractor, ExtractedEntity
from src.processing.entity_persistence import get_or_create_extracted_entity
from src.search.engine import SearchEngine
from src.search.normalization import search_blob


def _controlled_extractor(patterns):
    extractor = EntityExtractor.__new__(EntityExtractor)
    extractor._languages = ["mk", "sq", "en"]
    extractor._lexicon = extractor._load_lexicon()
    nlp = spacy.blank("xx")
    nlp.add_pipe("sentencizer")
    ruler = nlp.add_pipe("entity_ruler")
    ruler.add_patterns(patterns)
    extractor._nlp_models = {"xx": nlp, "en": nlp}
    return extractor


def _entity_session():
    engine = create_engine("sqlite:///:memory:")
    Entity.__table__.create(engine)
    return sessionmaker(bind=engine)()


def test_models_without_sentence_boundaries_get_sentencizer(monkeypatch):
    monkeypatch.setattr(spacy, "load", lambda _name: spacy.blank("xx"))
    extractor = EntityExtractor(languages=["mk"])

    assert "sentencizer" in extractor._nlp_models["en"].pipe_names
    assert "sentencizer" in extractor._nlp_models["xx"].pipe_names
    result = extractor.extract(
        "Христијан Мицкоски зборуваше. Потоа замина.",
        language="mk",
    )
    assert any(entity.name == "Христијан Мицкоски" for entity in result.entities)


def test_curated_alias_is_publishable_but_model_discovery_is_not():
    extractor = _controlled_extractor([
        {"label": "PER", "pattern": "Hristijan Mickoski"},
        {"label": "PER", "pattern": "John Example"},
    ])
    result = extractor.extract(
        "Hristijan Mickoski met John Example in Skopje.",
        language="en",
    )
    by_name = {entity.name: entity for entity in result.entities}

    curated = by_name["Христијан Мицкоски"]
    assert curated.publishable is True
    assert curated.confidence == 1.0
    assert curated.provenance == ["curated_lexicon"]
    assert "Hristijan Mickoski" in curated.matched_aliases

    discovered = by_name["John Example"]
    assert discovered.publishable is False
    assert discovered.confidence < 1.0
    assert discovered.provenance == ["spacy_ner"]


def test_observed_words_and_boilerplate_are_rejected():
    extractor = _controlled_extractor([
        {"label": "PER", "pattern": "Sipas"},
        {"label": "ORG", "pattern": "Flaka Media"},
        {"label": "ORG", "pattern": "Media Sociale"},
        {"label": "ORG", "pattern": "Агенцијата"},
    ])
    result = extractor.extract(
        "Sipas Flaka Media, Media Sociale. Агенцијата објави текст.",
        language="sq",
    )

    assert result.entities == []


def test_persistence_approves_curated_and_queues_model_discoveries():
    session = _entity_session()
    model_entity = ExtractedEntity(
        name="John Example",
        canonical_name="john example",
        entity_type="person",
        confidence=0.55,
        provenance=["spacy_ner"],
        publishable=False,
    )
    curated_entity = ExtractedEntity(
        name="Христијан Мицкоски",
        canonical_name="христијан мицкоски",
        entity_type="person",
        confidence=1.0,
        provenance=["curated_lexicon"],
        publishable=True,
        matched_aliases=["Hristijan Mickoski"],
    )

    discovered = get_or_create_extracted_entity(session, model_entity)
    curated = get_or_create_extracted_entity(session, curated_entity)
    session.commit()

    assert discovered.status == EntityStatus.NEEDS_REVIEW
    assert discovered.metadata_json["publishable"] is False
    assert discovered.metadata_json["confidence"] == 0.55
    assert curated.status == EntityStatus.APPROVED
    assert curated.metadata_json["publishable"] is True
    assert curated.metadata_json["aliases"] == ["Hristijan Mickoski"]


def test_client_search_requires_approved_status():
    session = _entity_session()
    rows = [
        ("Христијан Мицкоски", EntityStatus.APPROVED),
        ("Петар Петровски", EntityStatus.AUTO),
        ("Иван Ивановски", EntityStatus.NEEDS_REVIEW),
        ("Марко Марковски", EntityStatus.HIDDEN),
    ]
    for name, status in rows:
        canonical = EntityExtractor._canonicalize(name)
        session.add(Entity(
            name=name,
            canonical_name=canonical,
            search_text=search_blob(name, canonical),
            entity_type=EntityType.PERSON,
            status=status,
        ))
    session.commit()

    results = SearchEngine(session).search_entities("", limit=20)
    assert [entity.name for entity in results] == ["Христијан Мицкоски"]


def test_explicit_noise_list_is_narrow_and_deterministic():
    assert EntityExtractor.is_explicit_noise("Një")
    assert EntityExtractor.is_explicit_noise("Flaka Media")
    assert not EntityExtractor.is_explicit_noise("Христијан Мицкоски")
