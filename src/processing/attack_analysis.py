"""Conservative attack-relation extraction for MK/SQ/EN political coverage."""

import re
from typing import Iterable


CATEGORY_TERMS = {
    "corruption": [
        "corruption", "bribe", "tender", "abuse of office",
        "корупција", "поткуп", "тендер", "злоупотреба",
        "korrupsion", "ryshfet", "tender", "keqpërdor",
    ],
    "crime_legal": [
        "criminal", "crime", "investigation", "arrest", "trial", "accused",
        "криминал", "истрага", "апсење", "судење", "обвин",
        "krim", "hetim", "arrest", "gjykim", "akuz",
    ],
    "ethics_nepotism": [
        "nepotism", "conflict of interest", "clientelism",
        "непотизам", "судир на интереси", "клиентелизам",
        "nepotizëm", "konflikt interesi", "klientelizëm",
    ],
    "competence": [
        "incompetent", "failure", "resign", "scandal",
        "неспособ", "неуспех", "оставка", "скандал", "афера",
        "paaft", "dështim", "dorëheq", "skandal",
    ],
    "personal_attack": [
        "liar", "traitor", "shame", "hypocrite", "attacked",
        "лажго", "предавник", "срам", "лицемер", "нападна",
        "gënjeshtar", "tradhtar", "turp", "hipokrit", "sulmoi",
    ],
}

ATTACK_VERBS = [
    "accused", "accuses", "criticized", "criticises", "attacked", "called for resignation",
    "обвини", "обвинува", "критикува", "нападна", "побара оставка",
    "akuzoi", "akuzon", "kritikoi", "kritikon", "sulmoi", "kërkoi dorëheqjen",
]

QUOTE_RE = re.compile(r"[\"“„']([^\"“”„']{18,360})[\"“”„']")


GENERIC_ACCUSATION_TERMS = {
    "accused",
    "\u043e\u0431\u0432\u0438\u043d",
    "akuz",
}


def detect_attack_categories(text: str) -> list[str]:
    lowered = (text or "").casefold()
    categories = []
    for category, terms in CATEGORY_TERMS.items():
        matched = [term for term in terms if term.casefold() in lowered]
        if not matched:
            continue
        if category == "crime_legal" and not any(
            term.casefold() not in GENERIC_ACCUSATION_TERMS
            for term in matched
        ):
            continue
        categories.append(category)
    return categories


def analyze_attack_text(
    title: str,
    content: str,
    target: str,
    target_aliases: Iterable[str] = (),
    candidate_attackers: Iterable[str] = (),
) -> dict:
    """Extract only relations supported by an explicit sentence in the text."""
    full_text = ". ".join(part.strip().rstrip(".") for part in (title or "", content or "") if part and part.strip())
    target_forms = _unique([target, *target_aliases])
    sentences = _sentences(full_text)
    relevant = _relevant_sentence(sentences, target_forms)
    target_present = bool(relevant)
    explicit_verb = _first_marker(relevant or "", ATTACK_VERBS)
    categories = detect_attack_categories(relevant or "")

    attacker = None
    if target_present and explicit_verb:
        attacker = _attacker_before_marker(
            relevant,
            candidate_attackers,
            target_forms,
        )
    # A client-facing attack requires a supported relation: the target and an
    # explicit attack verb in one sentence, plus a named attacker before it.
    # This deliberately favors precision over recall for public-response work.
    is_attack = bool(target_present and explicit_verb and attacker)
    quote = _quote_from_text(relevant) if is_attack else None

    confidence = 0.0
    if target_present:
        confidence += 0.25
    if categories:
        confidence += 0.20
    if explicit_verb:
        confidence += 0.20
    if relevant:
        confidence += 0.15
    if attacker:
        confidence += 0.15
    if quote:
        confidence += 0.05

    return {
        "is_attack": is_attack,
        "target": target if target_present else None,
        "attacker": attacker,
        "allegation": _clip(relevant, 420) if is_attack else None,
        "quote": quote,
        "categories": categories,
        "confidence": round(min(confidence, 1.0), 2),
        "confidence_label": "high" if confidence >= 0.75 else "medium" if confidence >= 0.5 else "low",
        "extraction_basis": [
            label
            for present, label in (
                (target_present, "target_and_attack_in_same_sentence"),
                (bool(explicit_verb), "explicit_attack_verb"),
                (bool(categories), "attack_category_terms"),
                (bool(attacker), "named_attacker_before_attack_marker"),
                (bool(quote), "quoted_text"),
            )
            if present
        ],
    }


def _relevant_sentence(sentences: list[str], target_forms: list[str]) -> str | None:
    best = None
    best_score = 0
    all_markers = [*ATTACK_VERBS, *(term for terms in CATEGORY_TERMS.values() for term in terms)]
    for sentence in sentences:
        lowered = sentence.casefold()
        has_target = any(form.casefold() in lowered for form in target_forms if form)
        if not has_target:
            continue
        score = 2
        if any(marker.casefold() in lowered for marker in ATTACK_VERBS):
            score += 3
        if any(marker.casefold() in lowered for marker in all_markers):
            score += 2
        if score > best_score or (score == best_score and len(sentence) > len(best or "")):
            best = sentence
            best_score = score
    return best if best_score >= 4 else None


def _attacker_before_marker(
    sentence: str,
    candidates: Iterable[str],
    target_forms: list[str],
) -> str | None:
    lowered = sentence.casefold()
    marker = _first_marker(sentence, ATTACK_VERBS)
    marker_index = lowered.find(marker.casefold()) if marker else -1
    if marker_index < 0:
        return None
    target_keys = {value.casefold() for value in target_forms if value}
    ranked = []
    for candidate in _unique(candidates):
        if not candidate or candidate.casefold() in target_keys:
            continue
        candidate_index = lowered.rfind(candidate.casefold(), 0, marker_index)
        if candidate_index < 0:
            continue
        distance = marker_index - (candidate_index + len(candidate))
        if 0 <= distance <= 140:
            ranked.append((distance, -len(candidate), candidate))
    return min(ranked)[2] if ranked else None


def _first_marker(text: str, markers: Iterable[str]) -> str | None:
    lowered = (text or "").casefold()
    found = [
        (lowered.find(marker.casefold()), marker)
        for marker in markers
        if marker and marker.casefold() in lowered
    ]
    return min(found)[1] if found else None


def _quote_from_text(text: str | None) -> str | None:
    if not text:
        return None
    match = QUOTE_RE.search(text)
    return _clip(match.group(1).strip(), 320) if match else None


def _sentences(text: str) -> list[str]:
    return [
        part.strip()
        for part in re.split(r"(?<=[.!?])\s+|\n+", text or "")
        if part.strip()
    ]


def _unique(values: Iterable[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        clean = " ".join(str(value or "").split())
        key = clean.casefold()
        if clean and key not in seen:
            seen.add(key)
            result.append(clean)
    return result


def _clip(value: str | None, limit: int) -> str | None:
    if not value:
        return None
    clean = " ".join(value.split())
    return clean if len(clean) <= limit else clean[: limit - 3].rstrip() + "..."
