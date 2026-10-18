from src.intelligence.grounded_ai import (
    GroundedAI,
    _validate_evidence_support,
    _validate_payload,
)


def test_grounded_ai_is_local_without_key():
    result = GroundedAI(enabled=True, api_key=None).generate_json(
        task="Answer",
        instructions="Use evidence",
        evidence=[{"label": "S1", "claim": "Stored report"}],
    )
    assert result.accepted is False
    assert result.metadata()["mode"] == "local"


def test_grounding_accepts_only_labeled_factual_text():
    payload = {
        "answer": "The portal reported the allegation. [S1]",
        "summary": "One stored source carried the report. [S1]",
        "suggested_actions": ["Open the original article."],
        "claims": [{"text": "The portal reported it.", "citation_labels": ["S1"]}],
    }
    assert _validate_payload(payload, {"S1"}) == ""


def test_grounding_rejects_unsupported_sentence_and_label():
    uncited = {
        "answer": "The allegation is true.",
        "summary": "A source carried the report. [S1]",
        "suggested_actions": [],
        "claims": [{"text": "A report exists.", "citation_labels": ["S1"]}],
    }
    assert "without valid citations" in _validate_payload(uncited, {"S1"})

    outside_scope = {
        "answer": "A source carried the report. [S2]",
        "summary": "A source carried the report. [S2]",
        "suggested_actions": [],
        "claims": [{"text": "A report exists.", "citation_labels": ["S2"]}],
    }
    assert "without valid citations" in _validate_payload(outside_scope, {"S1"})


def test_grounding_requires_exact_quote_and_semantic_overlap():
    evidence = [{
        "label": "S1",
        "title": "Council meeting",
        "claim": "The council postponed the vote until Friday.",
    }]
    valid = {
        "answer": "The council postponed the vote until Friday. [S1]",
        "summary": "The vote was postponed until Friday. [S1]",
        "suggested_actions": [],
        "claims": [{
            "text": "The council postponed the vote until Friday.",
            "citation_labels": ["S1"],
            "evidence_quotes": [{
                "label": "S1",
                "quote": "The council postponed the vote until Friday.",
            }],
        }],
    }
    assert _validate_evidence_support(valid, evidence) == ""

    invented = {
        **valid,
        "answer": "The council approved a ten-million-euro contract. [S1]",
        "summary": "A large contract was approved. [S1]",
        "claims": [{
            "text": "The council approved a ten-million-euro contract.",
            "citation_labels": ["S1"],
            "evidence_quotes": [{
                "label": "S1",
                "quote": "The council postponed the vote until Friday.",
            }],
        }],
    }
    assert "not sufficiently supported" in _validate_evidence_support(invented, evidence)
