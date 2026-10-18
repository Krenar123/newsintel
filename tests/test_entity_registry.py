from pathlib import Path

import pytest

from src.processing.entities import EntityExtractor
from src.processing.entity_registry import (
    AliasRule,
    EntityRegistry,
    RegistryEntity,
    canonicalize,
)


def _registry(*entities):
    return EntityRegistry(entities, country_code="mk")


def _entity(name, entity_type, *aliases):
    return RegistryEntity(
        name=name,
        canonical_name=canonicalize(name),
        entity_type=entity_type,
        aliases=tuple(AliasRule.from_config(alias) for alias in (name, *aliases)),
    )


def test_registry_accepts_unicode_dash_and_spacing_variants():
    registry = _registry(_entity("ВМРО-ДПМНЕ", "organization", "VMRO-DPMNE"))

    matches = registry.match("VMRO – DPMNE и ВМРО ДПМНЕ одржаа средба.", language="mk")

    assert [match.entity.name for match in matches] == ["ВМРО-ДПМНЕ", "ВМРО-ДПМНЕ"]
    assert [match.alias.value for match in matches] == ["VMRO-DPMNE", "ВМРО-ДПМНЕ"]


def test_registry_prefers_longest_alias_without_double_counting():
    registry = _registry(
        _entity("Северна Македонија", "location", "Македонија"),
        _entity("Македонска опера", "organization"),
    )

    matches = registry.match("Северна Македонија и Македонска опера.", language="mk")

    assert [(match.entity.name, match.text) for match in matches] == [
        ("Северна Македонија", "Северна Македонија"),
        ("Македонска опера", "Македонска опера"),
    ]


def test_registry_rejects_alias_owned_by_two_entities():
    with pytest.raises(ValueError, match="Alias 'shared name'"):
        _registry(
            _entity("Прво лице", "person", "Shared Name"),
            _entity("Второ лице", "person", "Shared Name"),
        )


def test_context_guard_controls_ambiguous_alias():
    guarded = AliasRule.from_config({
        "value": "Центарот",
        "requires_any": ["управување со кризи", "ЦУК"],
        "excludes_any": ["трговски центар"],
    })
    registry = _registry(RegistryEntity(
        name="Центар за управување со кризи",
        canonical_name=canonicalize("Центар за управување со кризи"),
        entity_type="organization",
        aliases=(guarded,),
    ))

    assert registry.match("Центарот за управување со кризи објави предупредување.", language="mk")
    assert not registry.match("Трговски центарот понуди попуст.", language="mk")
    assert not registry.match("Центарот денес работи подолго.", language="mk")


def test_review_only_alias_is_extracted_but_not_publishable():
    review_only = AliasRule.from_config({"value": "Али", "publishable": False})
    registry = _registry(RegistryEntity(
        name="Али Ахмети",
        canonical_name=canonicalize("Али Ахмети"),
        entity_type="person",
        aliases=(review_only,),
    ))
    extractor = EntityExtractor.__new__(EntityExtractor)
    extractor._languages = ["mk"]
    extractor._registry = registry
    extractor._lexicon = list(registry.entities)
    extractor._nlp_models = {}

    result = extractor.extract("Али даде изјава пред присутните новинари.", language="mk")

    assert len(result.entities) == 1
    assert result.entities[0].name == "Али Ахмети"
    assert result.entities[0].publishable is False
    assert result.entities[0].decision_reasons == ["validated_registry_alias"]


def test_registry_extraction_works_without_statistical_model():
    registry = EntityRegistry.load(
        Path(__file__).resolve().parents[1] / "config" / "entities" / "north_macedonia.yaml"
    )
    extractor = EntityExtractor.__new__(EntityExtractor)
    extractor._languages = ["mk"]
    extractor._registry = registry
    extractor._lexicon = list(registry.entities)
    extractor._nlp_models = {}

    result = extractor.extract(
        "Христијан Мицкоски разговараше со Венко Филипче во Скопје.",
        language="mk",
    )

    assert {entity.name for entity in result.entities} == {
        "Христијан Мицкоски",
        "Венко Филипче",
        "Скопје",
    }
    assert all(entity.publishable for entity in result.entities)


def test_unreviewed_substrings_are_never_merged_automatically():
    candidates = {
        "али": {"name": "Али", "entity_type": "person"},
        "али ахмети": {"name": "Али Ахмети", "entity_type": "person"},
    }

    resolved = EntityExtractor._merge_similar(candidates)

    assert set(resolved) == {"али", "али ахмети"}


def test_acronym_aliases_are_case_sensitive_to_avoid_common_words():
    registry = EntityRegistry.load(
        Path(__file__).resolve().parents[1] / "config" / "entities" / "north_macedonia.yaml"
    )

    lower_names = {match.entity.name for match in registry.match(
        "Јас знам дека тој сад не е институција.", language="mk"
    )}
    upper_names = {match.entity.name for match in registry.match(
        "ЗНАМ разговараше со претставници на САД.", language="mk"
    )}

    assert "ЗНАМ" not in lower_names
    assert "САД" not in lower_names
    assert {"ЗНАМ", "САД"} <= upper_names


def test_non_acronym_aliases_remain_case_insensitive():
    registry = _registry(_entity("Христијан Мицкоски", "person", "Мицкоски"))

    matches = registry.match("мицкоски одговори на прашањето.", language="mk")

    assert [match.entity.name for match in matches] == ["Христијан Мицкоски"]
