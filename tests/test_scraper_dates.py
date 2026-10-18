import datetime

from src.ingestion.scraper import ArticleScraper


def test_macedonian_dotted_publication_date_with_separator():
    assert ArticleScraper._parse_date("29.07.2026 | 13:50") == datetime.datetime(
        2026, 7, 29, 13, 50
    )


def test_invalid_dotted_publication_date_is_rejected():
    assert ArticleScraper._parse_date("31.13.2026 | 13:50") is None
