import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.ingestion.url_filter import unknown_article_urls
from src.models.database import Article, Base, Source


class UnknownArticleUrlsTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.session = sessionmaker(bind=self.engine)()
        source = Source(
            name="Test Source",
            url="https://example.test",
            country_code="mk",
            language="mk",
        )
        self.session.add(source)
        self.session.flush()
        self.session.add(Article(
            source_id=source.id,
            url="https://example.test/stored-story/",
            title="Stored story",
            content_hash="a" * 64,
        ))
        self.session.commit()

    def tearDown(self):
        self.session.close()
        self.engine.dispose()

    def test_filters_exact_and_trailing_slash_variants(self):
        result = unknown_article_urls(self.session, [
            "https://example.test/stored-story",
            "https://example.test/stored-story/",
            "https://example.test/new-story",
        ])

        self.assertEqual(result, ["https://example.test/new-story"])

    def test_empty_discovery_is_empty(self):
        self.assertEqual(unknown_article_urls(self.session, []), [])


if __name__ == "__main__":
    unittest.main()
