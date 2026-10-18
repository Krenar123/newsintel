"""Provider-neutral, fail-closed AI generation over supplied evidence."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Optional

import structlog

from config import settings

logger = structlog.get_logger()

_CITATION_RE = re.compile(r"\[([SL]\d+)\]")


@dataclass
class GroundedGeneration:
    """Validated generation result with an auditable provider state."""

    accepted: bool
    payload: dict[str, Any] = field(default_factory=dict)
    provider: str = "local"
    model: Optional[str] = None
    reason: str = ""

    def metadata(self) -> dict[str, Any]:
        return {
            "mode": "ai" if self.accepted else "local",
            "provider": self.provider,
            "model": self.model,
            "grounding_validated": self.accepted,
            "reason": self.reason,
        }


class GroundedAI:
    """Call a configured model and reject output that escapes supplied evidence."""

    def __init__(
        self,
        enabled: Optional[bool] = None,
        provider: Optional[str] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
    ):
        self.enabled = settings.enable_ai_intelligence if enabled is None else enabled
        self.provider = (provider or settings.ai_provider or "anthropic").strip().lower()
        self.api_key = api_key or settings.ai_api_key or settings.anthropic_api_key
        self.model = model or settings.ai_model

    @property
    def available(self) -> bool:
        return bool(self.enabled and self.api_key and self.provider == "anthropic")

    def generate_json(
        self,
        *,
        task: str,
        instructions: str,
        evidence: list[dict[str, Any]],
        history: Optional[list[dict[str, str]]] = None,
        max_tokens: Optional[int] = None,
    ) -> GroundedGeneration:
        if not self.available:
            return GroundedGeneration(
                accepted=False,
                provider=self.provider,
                model=self.model,
                reason="AI is disabled or no supported provider key is configured.",
            )

        allowed_labels = {
            str(item.get("label"))
            for item in evidence
            if item.get("label")
        }
        if not allowed_labels:
            return GroundedGeneration(
                accepted=False,
                provider=self.provider,
                model=self.model,
                reason="No labeled evidence was available.",
            )

        evidence_json = json.dumps(evidence[:16], ensure_ascii=False, default=str)
        history_json = json.dumps((history or [])[-8:], ensure_ascii=False, default=str)
        prompt = f"""
TASK
{task}

INSTRUCTIONS
{instructions}

STRICT GROUNDING CONTRACT
- Use only the EVIDENCE below. Never use memory, outside knowledge, or assumptions.
- Every factual sentence in answer and summary must end with one or more labels such as [S1] or [L1].
- Recommendations must be clearly phrased as recommendations, not facts.
- Do not convert an allegation into a fact.
- A legal reference marked for review is only a research lead, never legal advice.
- If evidence is insufficient, say so explicitly and cite the evidence showing the limitation.
- Return JSON only with: answer, summary, suggested_actions, claims.
- claims is an array of objects with text, citation_labels, and evidence_quotes.
- evidence_quotes is an array of objects with label and quote. Each quote must be a
  short exact substring copied from that labeled evidence item.

CONVERSATION HISTORY
{history_json}

EVIDENCE
{evidence_json}
""".strip()

        try:
            raw = self._call_anthropic(prompt, max_tokens=max_tokens)
            payload = _parse_json_object(raw)
        except Exception as exc:
            logger.warning("grounded_ai_call_failed", provider=self.provider, error=str(exc))
            return GroundedGeneration(
                accepted=False,
                provider=self.provider,
                model=self.model,
                reason=f"Provider call failed: {type(exc).__name__}",
            )

        error = _validate_payload(payload, allowed_labels)
        if not error and settings.ai_grounding_required:
            error = _validate_evidence_support(payload, evidence)
        if error:
            logger.warning("grounded_ai_rejected", provider=self.provider, reason=error)
            return GroundedGeneration(
                accepted=False,
                provider=self.provider,
                model=self.model,
                reason=error,
            )
        return GroundedGeneration(
            accepted=True,
            payload=payload,
            provider=self.provider,
            model=self.model,
            reason="All generated factual text and claims reference supplied evidence labels.",
        )

    def summarize_article(
        self,
        *,
        title: str,
        text: str,
        output_language: str,
        sentence_count: int,
    ) -> GroundedGeneration:
        return self.generate_json(
            task=f"Summarize the article in {sentence_count} concise sentences in {output_language}.",
            instructions=(
                "Cover who, what, when, where, and why only when present. "
                "Use neutral wording. The answer and summary may be identical."
            ),
            evidence=[{
                "label": "S1",
                "title": title,
                "content": text[:12000],
            }],
            max_tokens=600,
        )

    def _call_anthropic(self, prompt: str, max_tokens: Optional[int]) -> str:
        import anthropic

        client = anthropic.Anthropic(
            api_key=self.api_key,
            timeout=settings.ai_timeout_seconds,
        )
        response = client.messages.create(
            model=self.model,
            max_tokens=max_tokens or settings.ai_max_output_tokens,
            temperature=0,
            system=(
                "You are the NewsIntel evidence editor. Never add facts outside the "
                "provided evidence and always obey the citation contract."
            ),
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(
            block.text
            for block in response.content
            if getattr(block, "type", "") == "text"
        ).strip()


def _parse_json_object(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("Provider did not return a JSON object")
    parsed = json.loads(text[start:end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("Provider response was not an object")
    return parsed


def _validate_payload(payload: dict[str, Any], allowed_labels: set[str]) -> str:
    answer = str(payload.get("answer") or "").strip()
    summary = str(payload.get("summary") or "").strip()
    claims = payload.get("claims")
    if not answer or not summary or not isinstance(claims, list):
        return "Required grounded fields were missing."
    for field_name, value in (("answer", answer), ("summary", summary)):
        if _invalid_cited_sentences(value, allowed_labels):
            return f"{field_name} contains factual text without valid citations."
    for claim in claims:
        if not isinstance(claim, dict) or not str(claim.get("text") or "").strip():
            return "A generated claim was malformed."
        labels = claim.get("citation_labels")
        if not isinstance(labels, list) or not labels:
            return "A generated claim had no citation."
        if any(str(label) not in allowed_labels for label in labels):
            return "A generated claim referenced evidence outside the permitted pack."
    actions = payload.get("suggested_actions", [])
    if not isinstance(actions, list):
        return "Suggested actions were malformed."
    payload["suggested_actions"] = [str(item).strip() for item in actions if str(item).strip()][:8]
    payload["claims"] = claims[:12]
    return ""


def _invalid_cited_sentences(text: str, allowed_labels: set[str]) -> list[str]:
    parts = [
        item.strip()
        for item in re.split(
            r"(?<=\])\s+|(?<=[.!?])\s+(?!\[[SL]\d+\])|\n+",
            text,
        )
        if item.strip()
    ]
    return [
        part
        for part in parts
        if not (set(_CITATION_RE.findall(part))
                and set(_CITATION_RE.findall(part)).issubset(allowed_labels))
    ]


def _validate_evidence_support(
    payload: dict[str, Any],
    evidence: list[dict[str, Any]],
) -> str:
    """Require exact source excerpts and lexical support for every generated claim."""
    evidence_by_label = {
        str(item.get("label")): _evidence_blob(item)
        for item in evidence
        if item.get("label")
    }
    claims = payload.get("claims") or []
    validated_claims: list[tuple[str, set[str]]] = []

    for claim in claims:
        claim_text = str(claim.get("text") or "").strip()
        labels = {str(label) for label in claim.get("citation_labels") or []}
        quotes = claim.get("evidence_quotes")
        if not isinstance(quotes, list) or not quotes:
            return "A generated claim had no exact evidence quote."

        quote_tokens: set[str] = set()
        quote_labels: set[str] = set()
        for quote_item in quotes:
            if not isinstance(quote_item, dict):
                return "A generated evidence quote was malformed."
            label = str(quote_item.get("label") or "")
            quote = _normalize_text(str(quote_item.get("quote") or ""))
            if label not in labels or label not in evidence_by_label:
                return "A generated evidence quote referenced the wrong source."
            if len(quote) < 12 or quote not in evidence_by_label[label]:
                return "A generated evidence quote was not found in the supplied source."
            quote_labels.add(label)
            quote_tokens.update(_content_tokens(quote))

        if not labels.issubset(quote_labels):
            return "A generated claim did not quote every cited source."
        claim_tokens = _content_tokens(claim_text)
        if claim_tokens and _overlap_ratio(claim_tokens, quote_tokens) < 0.35:
            return "A generated claim was not sufficiently supported by its exact quote."
        validated_claims.append((claim_text, labels))

    for field_name in ("answer", "summary"):
        for sentence in _cited_sentences(str(payload.get(field_name) or "")):
            labels = set(_CITATION_RE.findall(sentence))
            sentence_tokens = _content_tokens(_CITATION_RE.sub("", sentence))
            if not sentence_tokens:
                continue
            related = [
                _content_tokens(claim_text)
                for claim_text, claim_labels in validated_claims
                if labels.intersection(claim_labels)
            ]
            if not related or max(
                (_overlap_ratio(sentence_tokens, tokens) for tokens in related),
                default=0.0,
            ) < 0.18:
                return f"{field_name} contains wording not tied to a validated claim."
    return ""


def _evidence_blob(item: dict[str, Any]) -> str:
    values = []
    for key, value in item.items():
        if key in {"label", "url", "source_url"} or value is None:
            continue
        if isinstance(value, (dict, list)):
            values.append(json.dumps(value, ensure_ascii=False, default=str))
        else:
            values.append(str(value))
    return _normalize_text(" ".join(values))


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def _content_tokens(value: str) -> set[str]:
    stopwords = {
        "the", "and", "for", "that", "this", "with", "from", "was", "were",
        "are", "has", "have", "had", "until",
        "ова", "тоа", "овој", "кој", "која", "што", "беше", "има", "од", "со", "за",
        "dhe", "për", "per", "nga", "ishte", "është", "eshte", "kjo", "ajo",
    }
    return {
        token
        for token in re.findall(r"[\w\u0400-\u04ff]+", value.casefold(), flags=re.UNICODE)
        if len(token) >= 3 and token not in stopwords
    }


def _overlap_ratio(left: set[str], right: set[str]) -> float:
    return len(left.intersection(right)) / max(1, len(left))


def _cited_sentences(value: str) -> list[str]:
    return [
        item.strip()
        for item in re.split(r"(?<=\])\s+|\n+", value)
        if item.strip()
    ]
