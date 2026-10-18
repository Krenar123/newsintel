"""Validated, Unicode-aware registry for production entity matching.

The registry is deliberately deterministic. Curated aliases are the only
automatic publication path; statistical NER remains a discovery mechanism.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import yaml


ENTITY_TYPES = {"person", "organization", "location"}
_WORD_RE = re.compile(r"[^\W_]+", re.UNICODE)

def canonicalize(value: str) -> str:
    """Return a stable identity key while preserving non-Latin scripts."""
    value = unicodedata.normalize("NFKC", str(value or ""))
    value = value.replace("’", "'").replace("`", "'")
    value = re.sub(r"[‐‑‒–—−]", "-", value)
    value = " ".join(value.casefold().split())
    value = re.sub(r"\b(mr|mrs|ms|dr|prof|sr|jr)\b\.?\s*", "", value)
    return value.strip()


def alias_value(raw: str | dict) -> str:
    """Return the surface value from a simple or policy-bearing alias."""
    if isinstance(raw, dict):
        return str(raw.get("value", "")).strip()
    return str(raw or "").strip()


def _search_form(value: str) -> str:
    return " ".join(_WORD_RE.findall(canonicalize(value)))


def _looks_like_acronym(value: str) -> bool:
    letters = "".join(character for character in value if character.isalpha())
    return 2 <= len(letters) <= 5 and letters == letters.upper()


@dataclass(frozen=True)
class AliasRule:
    value: str
    languages: tuple[str, ...] = ()
    requires_any: tuple[str, ...] = ()
    excludes_any: tuple[str, ...] = ()
    publishable: bool = True
    case_sensitive: bool = False

    @classmethod
    def from_config(cls, raw: str | dict) -> "AliasRule":
        if isinstance(raw, str):
            value = raw.strip()
            data: dict = {}
        elif isinstance(raw, dict):
            data = raw
            value = alias_value(raw)
        else:
            raise ValueError(f"Alias must be a string or object, got {type(raw).__name__}")
        if not value:
            raise ValueError("Alias value cannot be empty")
        return cls(
            value=value,
            languages=tuple(str(item).casefold() for item in data.get("languages", []) if item),
            requires_any=tuple(str(item).casefold() for item in data.get("requires_any", []) if item),
            excludes_any=tuple(str(item).casefold() for item in data.get("excludes_any", []) if item),
            publishable=bool(data.get("publishable", True)),
            case_sensitive=bool(data.get("case_sensitive", _looks_like_acronym(value))),
        )

    @property
    def key(self) -> str:
        return _search_form(self.value)

    def allows(self, context: str, language: str) -> bool:
        if self.languages and language.casefold() not in self.languages:
            return False
        folded = canonicalize(context)
        if self.requires_any and not any(canonicalize(term) in folded for term in self.requires_any):
            return False
        if self.excludes_any and any(canonicalize(term) in folded for term in self.excludes_any):
            return False
        return True


@dataclass(frozen=True)
class RegistryEntity:
    name: str
    canonical_name: str
    entity_type: str
    aliases: tuple[AliasRule, ...]


@dataclass(frozen=True)
class RegistryMatch:
    entity: RegistryEntity
    alias: AliasRule
    start: int
    end: int
    text: str


class EntityRegistry:
    """Load, validate, and match a country entity registry."""

    def __init__(self, entities: Iterable[RegistryEntity], *, country_code: str = ""):
        self.entities = tuple(entities)
        self.country_code = country_code
        self.issues = self._validate()
        fatal = [issue for issue in self.issues if issue["severity"] == "error"]
        if fatal:
            detail = "; ".join(issue["message"] for issue in fatal[:5])
            raise ValueError(f"Invalid entity registry: {detail}")
        self._aliases_by_first_token: dict[str, list[tuple[tuple[str, ...], RegistryEntity, AliasRule]]] = {}
        for entity in self.entities:
            for alias in entity.aliases:
                tokens = tuple(_WORD_RE.findall(canonicalize(alias.value)))
                if not tokens:
                    continue
                self._aliases_by_first_token.setdefault(tokens[0], []).append((tokens, entity, alias))
        for candidates in self._aliases_by_first_token.values():
            candidates.sort(key=lambda item: (-len(item[0]), item[1].name))

    @classmethod
    def load(cls, path: Path) -> "EntityRegistry":
        if not path.exists():
            return cls(())
        with path.open(encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
        return cls.from_data(data)

    @classmethod
    def from_data(cls, data: dict) -> "EntityRegistry":
        entities: list[RegistryEntity] = []
        for row_number, item in enumerate(data.get("entities", []), start=1):
            name = str(item.get("name", "")).strip()
            entity_type = str(item.get("type", "")).strip()
            if not name:
                raise ValueError(f"Entity row {row_number} has no name")
            if entity_type not in ENTITY_TYPES:
                raise ValueError(f"Entity {name!r} has invalid type {entity_type!r}")
            aliases = [AliasRule.from_config(name)]
            aliases.extend(AliasRule.from_config(raw) for raw in item.get("aliases", []) or [])
            unique: dict[str, AliasRule] = {}
            for alias in aliases:
                unique.setdefault(alias.key, alias)
            entities.append(RegistryEntity(
                name=name,
                canonical_name=canonicalize(name),
                entity_type=entity_type,
                aliases=tuple(unique.values()),
            ))
        return cls(entities, country_code=str(data.get("country_code", "")))

    def _validate(self) -> list[dict[str, str]]:
        issues: list[dict[str, str]] = []
        canonical_owners: dict[tuple[str, str], str] = {}
        alias_owners: dict[str, set[str]] = {}
        for entity in self.entities:
            identity = (entity.canonical_name, entity.entity_type)
            if identity in canonical_owners:
                issues.append({
                    "severity": "error",
                    "code": "duplicate_canonical",
                    "message": f"{entity.name!r} duplicates {canonical_owners[identity]!r}",
                })
            canonical_owners[identity] = entity.name
            for alias in entity.aliases:
                alias_owners.setdefault(alias.key, set()).add(entity.name)
                if len(alias.key) < 2:
                    issues.append({
                        "severity": "error",
                        "code": "alias_too_short",
                        "message": f"Alias {alias.value!r} for {entity.name!r} is too short",
                    })
        for alias, owners in alias_owners.items():
            if len(owners) > 1:
                issues.append({
                    "severity": "error",
                    "code": "alias_collision",
                    "message": f"Alias {alias!r} belongs to {', '.join(sorted(owners))}",
                })
        return issues

    def match(self, text: str, *, language: str = "") -> list[RegistryMatch]:
        """Return longest non-overlapping matches in near-linear token time."""
        word_matches = list(_WORD_RE.finditer(text))
        tokens = [canonicalize(item.group(0)) for item in word_matches]
        accepted: list[RegistryMatch] = []
        token_index = 0
        while token_index < len(tokens):
            found_match = None
            for alias_tokens, entity, alias in self._aliases_by_first_token.get(tokens[token_index], []):
                end_index = token_index + len(alias_tokens)
                if tuple(tokens[token_index:end_index]) != alias_tokens:
                    continue
                if alias.case_sensitive:
                    observed = tuple(
                        unicodedata.normalize("NFKC", item.group(0))
                        for item in word_matches[token_index:end_index]
                    )
                    expected = tuple(_WORD_RE.findall(unicodedata.normalize("NFKC", alias.value)))
                    if observed != expected:
                        continue
                start = word_matches[token_index].start()
                end = word_matches[end_index - 1].end()
                context = self.context_for_span(text, start, end)
                if alias.allows(context, language):
                    found_match = RegistryMatch(
                        entity=entity,
                        alias=alias,
                        start=start,
                        end=end,
                        text=text[start:end],
                    )
                    break
            if found_match is None:
                token_index += 1
                continue
            accepted.append(found_match)
            token_index += len(tuple(_WORD_RE.findall(canonicalize(found_match.alias.value))))
        return accepted

    @staticmethod
    def context_for_span(text: str, start: int, end: int, *, limit: int = 500) -> str:
        left = max(
            text.rfind("\n", 0, start),
            text.rfind(".", 0, start),
            text.rfind("!", 0, start),
            text.rfind("?", 0, start),
        )
        sentence_start = 0 if left < 0 else left + 1
        right_positions = [
            position
            for marker in ("\n", ".", "!", "?")
            if (position := text.find(marker, end)) >= 0
        ]
        sentence_end = min(right_positions) + 1 if right_positions else len(text)
        context = " ".join(text[sentence_start:sentence_end].split())
        return context[:limit] + ("..." if len(context) > limit else "")
