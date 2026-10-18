import json

from scripts.evaluate_entity_annotations import evaluate


def test_real_article_evaluator_uses_only_labelled_requested_split(tmp_path):
    records = [
        {
            "record_id": "article-1",
            "split": "holdout",
            "language": "mk",
            "source": "Fixture Source",
            "text": "Христијан Мицкоски беше во Скопје.",
            "annotation": {
                "gold_entities": [
                    {"name": "Христијан Мицкоски", "type": "person"},
                    {"name": "Скопје", "type": "location"},
                ]
            },
        },
        {
            "record_id": "article-2",
            "split": "calibration",
            "language": "mk",
            "source": "Fixture Source",
            "text": "Венко Филипче даде изјава.",
            "annotation": {
                "gold_entities": [{"name": "Венко Филипче", "type": "person"}]
            },
        },
        {
            "record_id": "article-3",
            "split": "holdout",
            "language": "mk",
            "source": "Fixture Source",
            "text": "Ова сè уште не е означено.",
            "annotation": {"gold_entities": None},
        },
    ]
    path = tmp_path / "batch.jsonl"
    path.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
        encoding="utf-8",
    )

    report = evaluate([path], "holdout")

    assert report["records"] == 1
    assert report["sources"] == 1
    assert report["publishable"]["precision"] == 1.0
    assert report["publishable"]["recall"] == 1.0
    assert report["failures"] == []
