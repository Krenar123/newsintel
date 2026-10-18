"""
RSS Feed Fetcher — Primary ingestion method.

Parses RSS/Atom feeds from configured news sources. Handles deduplication
via content hashing, extracts article text when full content isn't in the
feed, and respects rate limits.
"""

import hashlib
import datetime
import time
from typing import Optional
from dataclasses import dataclass, field
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import feedparser
import httpx
from dateutil import parser as dateparser
import structlog

logger = structlog.get_logger()

TRACKING_QUERY_PREFIXES = ("utm_",)
TRACKING_QUERY_KEYS = {
    "fbclid", "gclid", "mc_cid", "mc_eid", "igshid", "ref",
    "ref_src", "utm", "cmp", "campaign",
}


@dataclass
class RawArticle:
    """Intermediate representation of an ingested article."""
    url: str
    title: str
    content: str = ""
    author: Optional[str] = None
    published_at: Optional[datetime.datetime] = None
    fetched_at: datetime.datetime = field(default_factory=datetime.datetime.utcnow)
    language: str = "en"
    source_name: str = ""
    source_url: str = ""
    source_country_code: str = ""
    source_type: str = "news"
    source_reliability_score: float = 0.5
    source_political_leaning: str = "unknown"
    source_ownership: Optional[str] = None
    image_url: Optional[str] = None
    raw_html: Optional[str] = None
    content_hash: str = ""
    rss_category: Optional[str] = None
    ingestion_method: str = "rss"
    platform: Optional[str] = None
    external_id: Optional[str] = None
    platform_account_id: Optional[str] = None
    platform_account_name: Optional[str] = None

    def compute_hash(self) -> str:
        """SHA-256 of title + content for deduplication."""
        self.url = normalize_url(self.url)
        text = (
            f"{normalize_text_for_hash(self.title)}|"
            f"{normalize_text_for_hash(self.content)}"
        )
        self.content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        return self.content_hash


def normalize_url(url: str) -> str:
    """Normalize article URLs so tracking variants deduplicate correctly."""
    if not url:
        return ""
    parsed = urlparse(url.strip())
    scheme = (parsed.scheme or "https").lower()
    netloc = parsed.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    query = []
    for key, value in parse_qsl(parsed.query, keep_blank_values=False):
        key_lower = key.lower()
        if key_lower in TRACKING_QUERY_KEYS:
            continue
        if any(key_lower.startswith(prefix) for prefix in TRACKING_QUERY_PREFIXES):
            continue
        query.append((key, value))
    path = parsed.path.rstrip("/") or "/"
    return urlunparse((scheme, netloc, path, "", urlencode(query), ""))


def normalize_text_for_hash(value: str) -> str:
    """Normalize whitespace/punctuation noise before content hashing."""
    if not value:
        return ""
    return " ".join(
        "".join(ch.lower() if ch.isalnum() else " " for ch in value).split()
    )


class RSSFetcher:
    """Fetches and parses RSS/Atom feeds from news sources."""

    def __init__(
        self,
        http_client: Optional[httpx.Client] = None,
        delay_seconds: float = 1.0,
        max_articles: int = 50,
        allow_insecure_ssl_fallback: bool = True,
    ):
        self.allow_insecure_ssl_fallback = allow_insecure_ssl_fallback
        self.client = http_client or httpx.Client(
            timeout=30.0,
            follow_redirects=True,
            verify=_certifi_verify(),
            headers={
                "User-Agent": (
                    "NewsIntel/1.0 (News Aggregator; "
                    "+https://github.com/newsintel)"
                )
            },
        )
        self.delay = delay_seconds
        self.max_articles = max_articles

    def fetch_feed(
        self,
        feed_url: str,
        source_name: str = "",
        source_url: str = "",
        source_country_code: str = "",
        source_type: str = "news",
        source_reliability_score: float = 0.5,
        source_political_leaning: str = "unknown",
        source_ownership: Optional[str] = None,
        language: str = "en",
        default_category: Optional[str] = None,
    ) -> list[RawArticle]:
        """
        Fetch and parse a single RSS/Atom feed.

        Returns a list of RawArticle objects ready for processing.
        """
        logger.info("fetching_feed", url=feed_url, source=source_name)
        fetched_at = datetime.datetime.utcnow()

        try:
            response = self.client.get(feed_url)
            response.raise_for_status()
        except httpx.HTTPError as e:
            if self.allow_insecure_ssl_fallback and "CERTIFICATE_VERIFY_FAILED" in str(e):
                response = self._fetch_feed_insecure(feed_url, str(e))
                if response is None:
                    return []
            else:
                logger.error("feed_fetch_failed", url=feed_url, error=str(e))
                return []

        feed = feedparser.parse(response.text)

        if feed.bozo and not feed.entries:
            logger.warning(
                "feed_parse_error",
                url=feed_url,
                error=str(feed.bozo_exception),
            )
            return []

        articles = []
        for entry in feed.entries[: self.max_articles]:
            article = self._parse_entry(
                entry,
                source_name,
                source_url,
                source_country_code,
                source_type,
                source_reliability_score,
                source_political_leaning,
                source_ownership,
                language,
                default_category,
            )
            if article:
                article.fetched_at = fetched_at
                articles.append(article)

        logger.info(
            "feed_parsed",
            url=feed_url,
            article_count=len(articles),
        )
        return articles

    def fetch_all_feeds(self, source_config: dict) -> list[RawArticle]:
        """
        Fetch all RSS feeds for a single source from its config dict.

        Expected format:
            {
                "name": "MKD.mk",
                "url": "https://mkd.mk",
                "language": "mk",
                "rss_feeds": [
                    {"url": "https://mkd.mk/rss", "category": "general"}
                ]
            }
        """
        all_articles = []
        feeds = source_config.get("rss_feeds", [])

        for feed_cfg in feeds:
            articles = self.fetch_feed(
                feed_url=feed_cfg["url"],
                source_name=source_config.get("name", ""),
                source_url=source_config.get("url", ""),
                source_country_code=source_config.get("country_code", ""),
                source_type=source_config.get("source_type", "news"),
                source_reliability_score=source_config.get("reliability_score", 0.5),
                source_political_leaning=source_config.get("political_leaning", "unknown"),
                source_ownership=source_config.get("ownership"),
                language=source_config.get("language", "en"),
                default_category=feed_cfg.get("category"),
            )
            all_articles.extend(articles)

            # Rate-limit between feeds
            if self.delay > 0 and len(feeds) > 1:
                time.sleep(self.delay)

        return all_articles

    def _parse_entry(
        self,
        entry: feedparser.FeedParserDict,
        source_name: str,
        source_url: str,
        source_country_code: str,
        source_type: str,
        source_reliability_score: float,
        source_political_leaning: str,
        source_ownership: Optional[str],
        language: str,
        default_category: Optional[str],
    ) -> Optional[RawArticle]:
        """Parse a single feed entry into a RawArticle."""

        # URL is required
        url = entry.get("link", "").strip()
        if not url:
            return None

        # Title
        title = entry.get("title", "").strip()
        if not title:
            return None

        # Content — try multiple fields
        content = ""
        if "content" in entry and entry.content:
            content = entry.content[0].get("value", "")
        if not content:
            content = entry.get("summary", "") or entry.get("description", "")

        # Strip HTML tags for plain text (keep raw_html separately)
        raw_html = content
        content = self._strip_html(content)

        # Author
        author = entry.get("author") or entry.get("dc_creator")

        # Published date
        published_at = self._parse_date(entry)

        # Image
        image_url = self._extract_image(entry)

        # Category from feed
        rss_category = default_category
        if "tags" in entry and entry.tags:
            rss_category = entry.tags[0].get("term", default_category)

        article = RawArticle(
            url=url,
            title=title,
            content=content,
            author=author,
            published_at=published_at,
            fetched_at=datetime.datetime.utcnow(),
            language=language,
            source_name=source_name,
            source_url=source_url,
            source_country_code=source_country_code,
            source_type=source_type,
            source_reliability_score=source_reliability_score,
            source_political_leaning=source_political_leaning,
            source_ownership=source_ownership,
            image_url=image_url,
            raw_html=raw_html,
            rss_category=rss_category,
        )
        article.compute_hash()

        return article

    @staticmethod
    def _strip_html(html: str) -> str:
        """Remove HTML tags, returning plain text."""
        if not html:
            return ""
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "lxml")
        # Remove script and style elements
        for element in soup(["script", "style"]):
            element.decompose()
        text = soup.get_text(separator=" ", strip=True)
        # Collapse whitespace
        return " ".join(text.split())

    @staticmethod
    def _parse_date(entry) -> Optional[datetime.datetime]:
        """Extract and parse publication date from feed entry."""
        for field_name in ("published", "updated", "created"):
            raw = entry.get(field_name)
            if raw:
                try:
                    return dateparser.parse(raw)
                except (ValueError, TypeError):
                    continue
        # feedparser also provides *_parsed tuples
        for field_name in ("published_parsed", "updated_parsed"):
            parsed = entry.get(field_name)
            if parsed:
                try:
                    return datetime.datetime(*parsed[:6])
                except (TypeError, ValueError):
                    continue
        return None

    @staticmethod
    def _extract_image(entry) -> Optional[str]:
        """Try to extract a thumbnail/image URL from feed entry."""
        # media:thumbnail
        if "media_thumbnail" in entry and entry.media_thumbnail:
            return entry.media_thumbnail[0].get("url")
        # media:content
        if "media_content" in entry and entry.media_content:
            for media in entry.media_content:
                if media.get("medium") == "image" or "image" in media.get(
                    "type", ""
                ):
                    return media.get("url")
        # enclosure
        if "links" in entry:
            for link in entry.links:
                if link.get("type", "").startswith("image/"):
                    return link.get("href")
        return None

    def close(self):
        self.client.close()

    def _fetch_feed_insecure(self, feed_url: str, original_error: str) -> Optional[httpx.Response]:
        logger.warning(
            "feed_ssl_verify_failed_retrying_insecure",
            url=feed_url,
            error=original_error,
        )
        try:
            with httpx.Client(
                timeout=30.0,
                follow_redirects=True,
                verify=False,
                headers=self.client.headers,
            ) as client:
                response = client.get(feed_url)
                response.raise_for_status()
                return response
        except httpx.HTTPError as e:
            logger.error("feed_fetch_failed", url=feed_url, error=str(e))
            return None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def _certifi_verify():
    try:
        import certifi
        return certifi.where()
    except Exception:
        return True
