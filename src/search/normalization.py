"""Search normalization for Macedonian Cyrillic/Latin matching."""

from __future__ import annotations

import re
import unicodedata


CYR_TO_LAT = {
    "а": "a",
    "б": "b",
    "в": "v",
    "г": "g",
    "д": "d",
    "ѓ": "gj",
    "е": "e",
    "ж": "zh",
    "з": "z",
    "ѕ": "dz",
    "и": "i",
    "ј": "j",
    "к": "k",
    "л": "l",
    "љ": "lj",
    "м": "m",
    "н": "n",
    "њ": "nj",
    "о": "o",
    "п": "p",
    "р": "r",
    "с": "s",
    "т": "t",
    "ќ": "kj",
    "у": "u",
    "ф": "f",
    "х": "h",
    "ц": "c",
    "ч": "ch",
    "џ": "dz",
    "ш": "sh",
}

LAT_TO_CYR_DIGRAPHS = [
    ("dzh", "џ"),
    ("gj", "ѓ"),
    ("kj", "ќ"),
    ("zh", "ж"),
    ("dz", "ѕ"),
    ("lj", "љ"),
    ("nj", "њ"),
    ("ch", "ч"),
    ("sh", "ш"),
]

LAT_TO_CYR = {
    "a": "а",
    "b": "б",
    "v": "в",
    "g": "г",
    "d": "д",
    "e": "е",
    "z": "з",
    "i": "и",
    "j": "ј",
    "k": "к",
    "l": "л",
    "m": "м",
    "n": "н",
    "o": "о",
    "p": "п",
    "r": "р",
    "s": "с",
    "t": "т",
    "u": "у",
    "f": "ф",
    "h": "х",
    "c": "ц",
}


def normalize_text(value: str | None) -> str:
    """Lowercase, remove accents, and collapse punctuation for search."""
    if not value:
        return ""
    value = unicodedata.normalize("NFKD", value)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.lower()
    value = value.replace("đ", "dz").replace("ǵ", "gj").replace("ḱ", "kj")
    return " ".join(re.sub(r"[^\w]+", " ", value, flags=re.UNICODE).split())


def cyrillic_to_latin(value: str | None) -> str:
    normalized = normalize_text(value)
    return "".join(CYR_TO_LAT.get(ch, ch) for ch in normalized)


def latin_to_cyrillic(value: str | None) -> str:
    text = normalize_text(value)
    output: list[str] = []
    index = 0
    while index < len(text):
        matched = False
        for latin, cyrillic in LAT_TO_CYR_DIGRAPHS:
            if text.startswith(latin, index):
                output.append(cyrillic)
                index += len(latin)
                matched = True
                break
        if matched:
            continue
        output.append(LAT_TO_CYR.get(text[index], text[index]))
        index += 1
    return "".join(output)


def search_variants(value: str | None) -> list[str]:
    """Return unique normalized search forms for a query or stored text."""
    variants = [
        normalize_text(value),
        cyrillic_to_latin(value),
        latin_to_cyrillic(value),
    ]
    return [item for index, item in enumerate(variants) if item and item not in variants[:index]]


def search_blob(*values: str | None) -> str:
    """Build a stored search blob containing original, Latin, and Cyrillic forms."""
    parts: list[str] = []
    for value in values:
        parts.extend(search_variants(value))
    return " ".join(dict.fromkeys(parts))
