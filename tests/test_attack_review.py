from types import SimpleNamespace

from src.api.main import _apply_attack_review, _clean_saved_search_filters


def _detail():
    return {
        "is_attack": True,
        "attacker": "SDSM",
        "target": "Hristijan Mickoski",
        "allegation": "SDSM criticized Hristijan Mickoski over policy failure.",
        "quote": None,
        "categories": ["competence"],
    }


def test_rejected_attack_review_removes_client_facing_relation():
    review = SimpleNamespace(id=4, status="rejected", notes="Neutral report")

    result = _apply_attack_review(_detail(), review)

    assert result["is_attack"] is False
    assert result["attacker"] is None
    assert result["allegation"] is None
    assert result["categories"] == []
    assert result["review_status"] == "rejected"


def test_corrected_attack_review_replaces_supported_fields():
    review = SimpleNamespace(
        id=5,
        status="corrected",
        notes="Corrected after source review",
        corrected_attacker="Opposition coalition",
        corrected_target=None,
        corrected_allegation="The coalition requested accountability for the policy outcome.",
        corrected_categories=["policy_failure"],
    )

    result = _apply_attack_review(_detail(), review)

    assert result["is_attack"] is True
    assert result["attacker"] == "Opposition coalition"
    assert result["target"] == "Hristijan Mickoski"
    assert result["categories"] == ["policy_failure"]


def test_saved_search_filter_allowlist_drops_untrusted_values():
    result = _clean_saved_search_filters({
        "category": "politics",
        "exact_phrase": True,
        "limit": 10_000,
        "user_id": 99,
        "nested": {"unsafe": True},
    })

    assert result == {"category": "politics", "exact_phrase": True}
