from scripts.evaluate_rag_retrieval import evaluate_dataset
from src.intelligence.retrieval import RetrievalDocument


def test_correct_abstentions_do_not_reduce_answerable_query_mrr():
    documents = [
        RetrievalDocument(document_id=1, title="Собрание расправа за буџет", source_id=1),
    ]
    report = evaluate_dataset(documents, [
        {
            "id": "answerable",
            "query": "Собрание буџет",
            "relevant_document_ids": [1],
        },
        {
            "id": "unsupported",
            "query": "марсовска мисија",
            "relevant_document_ids": [],
        },
    ])

    assert report["metrics"]["mrr"] == 1.0
    assert report["metrics"]["abstention_accuracy"] == 1.0
    assert report["metrics"]["forbidden_document_hits"] == 0


def test_evaluator_applies_allowed_scope_before_ranking():
    documents = [
        RetrievalDocument(document_id=1, title="Дозволена економска анализа", source_id=1),
        RetrievalDocument(document_id=2, title="СДСМ економски пакет", source_id=2),
    ]
    report = evaluate_dataset(documents, [{
        "id": "scope",
        "query": "СДСМ економски пакет",
        "allowed_document_ids": [1],
        "relevant_document_ids": [],
        "forbidden_document_ids": [2],
    }])

    row = report["queries"][0]
    assert row["returned_ids"] == []
    assert row["forbidden_hits"] == []
    assert row["abstained"] is True
