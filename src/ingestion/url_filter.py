"""Database-aware URL filtering for direct scraper discovery."""

from sqlalchemy.orm import Session

from src.models.database import Article


def unknown_article_urls(session: Session, urls: list[str]) -> list[str]:
    """Return discovered URLs that are not already stored, ignoring a trailing slash."""
    if not urls:
        return []
    variants = set()
    for url in urls:
        base = url.rstrip("/")
        variants.update({url, base, f"{base}/"})
    existing = {
        row[0].rstrip("/")
        for row in session.query(Article.url).filter(Article.url.in_(variants)).all()
    }
    return [url for url in urls if url.rstrip("/") not in existing]
