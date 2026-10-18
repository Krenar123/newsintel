from src.processing.attack_analysis import analyze_attack_text, detect_attack_categories


def test_explicit_named_attacker_is_supported():
    result = analyze_attack_text(
        title="Filipce accused Mickoski of corruption",
        content="Venko Filipce accused Hristijan Mickoski of corruption in office.",
        target="Hristijan Mickoski",
        target_aliases=["Mickoski"],
        candidate_attackers=["Venko Filipce", "Hristijan Mickoski"],
    )

    assert result["is_attack"] is True
    assert result["attacker"] == "Venko Filipce"
    assert result["target"] == "Hristijan Mickoski"
    assert result["confidence_label"] == "high"


def test_target_speaking_about_someone_else_is_not_the_attack_target():
    result = analyze_attack_text(
        title="Mickoski accused Filipce of corruption",
        content="Hristijan Mickoski accused Venko Filipce of corruption.",
        target="Hristijan Mickoski",
        target_aliases=["Mickoski"],
        candidate_attackers=["Hristijan Mickoski", "Venko Filipce"],
    )

    assert result["is_attack"] is False
    assert result["attacker"] is None


def test_unrelated_negative_language_does_not_create_an_attack():
    result = analyze_attack_text(
        title="Mickoski attended an event",
        content=(
            "Hristijan Mickoski attended an economic event. "
            "In a separate report, police opened a criminal investigation into a theft."
        ),
        target="Hristijan Mickoski",
        target_aliases=["Mickoski"],
        candidate_attackers=["Police"],
    )

    assert result["is_attack"] is False
    assert result["categories"] == []


def test_generic_accusation_word_is_not_a_criminal_allegation_category():
    categories = detect_attack_categories("SDSM accused Mickoski over water-quality reporting.")

    assert "crime_legal" not in categories
