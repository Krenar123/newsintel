import datetime

from src.intelligence.retrieval import RetrievalDocument, query_terms, rank_documents


NOW = datetime.datetime(2026, 10, 18, 12, 0, 0)


def document(document_id, title, *, content="", summary="", entities=(),
             source="Source", source_id=1, days_old=1, reliability=0.8):
    return RetrievalDocument(
        document_id=document_id,
        title=title,
        content=content,
        summary=summary,
        entity_names=tuple(entities),
        source_name=source,
        source_id=source_id,
        published_at=NOW - datetime.timedelta(days=days_old),
        reliability_score=reliability,
        language="mk",
    )


def test_cyrillic_query_retrieves_latin_entity_alias():
    outcome = rank_documents(
        "Што е најново за Мицкоски?",
        [
            document(1, "Government announces cabinet meeting",
                     entities=("Hristijan Mickoski",)),
            document(2, "Sports club announces new coach", source_id=2),
        ],
        now=NOW,
    )
    assert outcome.abstained is False
    assert outcome.results[0].document.document_id == 1
    assert outcome.results[0].entity_score > 0


def test_exact_title_and_entity_evidence_outrank_fresh_body_noise():
    outcome = rank_documents(
        "ВМРО ДПМНЕ буџет",
        [
            document(1, "ВМРО-ДПМНЕ го претстави предлог-буџетот",
                     summary="Партијата ги објави приоритетите.",
                     entities=("ВМРО-ДПМНЕ",), days_old=8),
            document(2, "Дневен преглед",
                     content="Буџетот беше спомнат во долга листа на теми.",
                     source_id=2, days_old=0),
        ],
        now=NOW,
    )
    assert outcome.results[0].document.document_id == 1
    assert outcome.results[0].phrase_score > 0 or outcome.results[0].entity_score > 0


def test_unrelated_quality_source_cannot_enter_results():
    outcome = rank_documents(
        "уставни измени",
        [document(1, "Football results",
                  content="A completely unrelated sports report.",
                  reliability=1.0)],
        now=NOW,
    )
    assert outcome.abstained is True
    assert outcome.results == ()


def test_source_cap_and_diagnostics_are_enforced():
    documents = [
        document(index, f"Корупција истрага документ {index}",
                 source="Portal A" if index <= 5 else "Portal B",
                 source_id=1 if index <= 5 else 2, days_old=index)
        for index in range(1, 8)
    ]
    outcome = rank_documents(
        "корупција истрага", documents, limit=6, max_per_source=2, now=NOW
    )
    source_ids = [item.document.source_id for item in outcome.results]
    assert source_ids.count(1) <= 2
    assert source_ids.count(2) <= 2
    assert outcome.diagnostics()["engine"] == "hybrid_bm25f_v1"
    assert outcome.diagnostics()["considered_count"] == 7


def test_query_terms_include_cross_script_variants_without_duplicates():
    terms = query_terms("Христијан Мицкоски")
    assert "христијан" in terms
    assert "hristijan" in terms
    assert len(terms) == len(set(terms))

    stopword_terms = query_terms("what are the latest mentions about me")
    assert "the" not in stopword_terms
    assert "тхе" not in stopword_terms
    assert "ме" not in stopword_terms


def test_timezone_aware_dates_are_scored_without_mixing_naive_datetimes():
    aware_now = datetime.datetime(2026, 10, 18, 12, 0, tzinfo=datetime.timezone.utc)
    item = RetrievalDocument(
        document_id=9,
        title="Уставни измени",
        published_at=aware_now - datetime.timedelta(hours=2),
    )
    outcome = rank_documents("уставни измени", [item], now=aware_now.replace(tzinfo=None))
    assert outcome.abstained is False
    assert outcome.results[0].freshness_score > 0
