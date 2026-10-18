"""
Website scraper for sources that publish articles outside RSS.

The scraper has two jobs:
  1. Crawl configured listing pages and discover article URLs.
  2. Extract article text/metadata using per-source CSS selectors, with a
     readability fallback when selectors are incomplete.

It returns the same RawArticle shape as RSS ingestion so downstream
deduplication, NLP, alerts, and reporting stay unified.
"""

import datetime
import json
import re
import time
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from dateutil import parser as dateparser
import structlog

from src.ingestion.rss_fetcher import RawArticle, normalize_url, _certifi_verify

logger = structlog.get_logger()

DEFAULT_EXCLUDE_PATTERNS = [
    re.compile(pattern) for pattern in [
        r"\.(pdf|jpg|jpeg|png|gif|webp|zip|rar)$",
        r"/(kontakt|contact|impresum|impressum|marketing|team|about|privacy|terms)/?$",
        r"/(privacy-policy|politika-na-privatnost|pravila-i-uslovi|pravila-i-uslovi-na-koristene|terms-and-conditions)/?$",
        r"/(za-birn|za-birn-makedonija|za-nas|about-us)/?$",
        r"/(live-tv|najnovi-vesti|latest-news|archive|arhiva|resursi)/?$",
        r"/(sdk-magazin|vesti|mk|soopstenija|studio|sport|kultura|zanimlivosti|crna-hronika)/?$",
        r"/(makedonija|ekonomija|svet|region|hronika|republika|magazin|scena|tehnologija)/?$",
        r"(cenovnik|tsenovnik|reklamirane|advertising|kodeks|protsedura-za-zhalbi|uslovi-za-prezemanje)",
        r"(newsletter|e-bilten|bilten|cdn-cgi)",
        r"/feeds?$",
        r"/(sq|sr|tr|bg|el|en|it|de|fr|es)$",
    ]
]

DEFAULT_BAD_TITLE_PATTERNS = [
    re.compile(pattern, re.IGNORECASE) for pattern in [
        r"^(privacy policy|terms|contact|about|live-tv|archive|resources)$",
        r"^(najnovi vesti|latest news|vesti|sdk magazin)$",
        r"(privacy policy|politika na privatnost|pravila i uslovi)",
    ]
]

DEFAULT_BAD_CONTENT_PATTERNS = [
    re.compile(pattern, re.IGNORECASE) for pattern in [
        r"available only to subscribers",
        r"content is available only to subscribers",
        r"Веста е достапна само за претплатниците",
        r"Логирајте се или контактирајте",
    ]
]

CONTENT_NOISE_SELECTORS = [
    "aside",
    "footer",
    "nav",
    "form",
    ".related",
    "[class*='related-post']",
    "[id*='related-post']",
    "[class*='recommended']",
    "[class*='share-buttons']",
    "[class*='social-share']",
    "[class*='newsletter']",
    "[class*='advertisement']",
    "[class*='comments-area']",
    ".code-block",
    ".najcitani",
]


@dataclass
class ScrapedContent:
    """Result of scraping a single article URL."""
    url: str
    title: str
    content: str
    html: str
    word_count: int
    success: bool
    author: Optional[str] = None
    published_at: Optional[datetime.datetime] = None
    image_url: Optional[str] = None
    error: Optional[str] = None


class ArticleScraper:
    """Extract article pages and crawl configured source listing pages."""

    def __init__(
        self,
        http_client: Optional[httpx.Client] = None,
        delay_seconds: float = 2.0,
        max_articles_per_source: int = 25,
        allow_insecure_ssl_fallback: bool = True,
    ):
        self.allow_insecure_ssl_fallback = allow_insecure_ssl_fallback
        self.client = http_client or httpx.Client(
            timeout=30.0,
            follow_redirects=True,
            verify=_certifi_verify(),
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (compatible; NewsIntel/1.0; "
                    "+https://github.com/newsintel)"
                ),
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "mk,en-US;q=0.9,en;q=0.8,sq;q=0.7",
            },
        )
        self.delay = delay_seconds
        self.max_articles_per_source = max_articles_per_source
        self._last_request_time = 0.0

    def scrape_source(
        self,
        source_config: dict,
        article_urls: Optional[list[str]] = None,
        max_articles: Optional[int] = None,
    ) -> list[RawArticle]:
        """Crawl and scrape all configured article pages for one source."""
        scraper_cfg = source_config.get("scraper") or {}
        if not scraper_cfg.get("enabled", False):
            return []

        article_urls = article_urls if article_urls is not None else self.discover_article_urls(source_config)
        article_limit = max_articles or self.max_articles_per_source
        articles = []

        for url in article_urls[:article_limit]:
            result = self.scrape_article(url, scraper_cfg)
            if not result.success:
                continue

            article = RawArticle(
                url=result.url,
                title=result.title,
                content=result.content,
                author=result.author,
                published_at=result.published_at,
                fetched_at=datetime.datetime.utcnow(),
                language=source_config.get("language", "en"),
                source_name=source_config.get("name", ""),
                source_url=source_config.get("url", ""),
                source_country_code=source_config.get("country_code", ""),
                source_type=source_config.get("source_type", "news"),
                source_reliability_score=source_config.get("reliability_score", 0.5),
                source_political_leaning=source_config.get("political_leaning", "unknown"),
                source_ownership=source_config.get("ownership"),
                image_url=result.image_url,
                raw_html=result.html,
                rss_category=scraper_cfg.get("category", "general"),
                ingestion_method="scrape",
            )
            article.compute_hash()
            articles.append(article)

        logger.info(
            "source_scraped",
            source=source_config.get("name"),
            discovered=len(article_urls),
            articles=len(articles),
        )
        return articles

    def discover_article_urls(self, source_config: dict) -> list[str]:
        """Discover article links from configured listing pages."""
        scraper_cfg = source_config.get("scraper") or {}
        listing_urls = scraper_cfg.get("listing_urls") or [source_config.get("url")]
        link_selectors = scraper_cfg.get("article_link_selectors") or [
            "article a[href]",
            "h1 a[href]",
            "h2 a[href]",
            "h3 a[href]",
        ]
        include_patterns = [
            re.compile(pattern) for pattern in scraper_cfg.get("include_url_patterns", [])
        ]
        exclude_patterns = DEFAULT_EXCLUDE_PATTERNS + [
            re.compile(pattern) for pattern in scraper_cfg.get("exclude_url_patterns", [])
        ]

        discovered: list[str] = []
        seen: set[str] = set()
        source_domain = urlparse(source_config.get("url", "")).netloc.replace("www.", "")

        for listing_url in listing_urls:
            html = self._fetch_text(listing_url)
            if not html:
                continue

            soup = BeautifulSoup(html, "lxml")
            for selector in link_selectors:
                for link in soup.select(selector):
                    href = link.get("href")
                    if not href:
                        continue

                    absolute = normalize_url(urljoin(listing_url, href.split("#")[0]))
                    parsed = urlparse(absolute)
                    if parsed.scheme not in {"http", "https"}:
                        continue
                    if source_domain and parsed.netloc.replace("www.", "") != source_domain:
                        continue
                    if absolute in seen:
                        continue
                    reject_reason = self._url_reject_reason(
                        absolute,
                        source_domain=source_domain,
                        include_patterns=include_patterns,
                        exclude_patterns=exclude_patterns,
                    )
                    if reject_reason:
                        continue

                    seen.add(absolute)
                    discovered.append(absolute)

                    if len(discovered) >= self.max_articles_per_source:
                        return discovered

        return discovered

    def scrape_article(self, url: str, scraper_config: Optional[dict] = None) -> ScrapedContent:
        """Fetch and extract article content from a URL."""
        scraper_config = scraper_config or {}
        html = self._fetch_text(url)
        if not html:
            return ScrapedContent(
                url=url,
                title="",
                content="",
                html="",
                word_count=0,
                success=False,
                error="fetch_failed",
            )

        try:
            soup = BeautifulSoup(html, "lxml")
            selectors = scraper_config.get("selectors") or {}
            canonical_url = self._canonical_url(soup, url)
            exclude_patterns = DEFAULT_EXCLUDE_PATTERNS + [
                re.compile(pattern) for pattern in scraper_config.get("exclude_url_patterns", [])
            ]
            reject_reason = self._url_reject_reason(
                canonical_url,
                source_domain=urlparse(url).netloc.replace("www.", ""),
                include_patterns=[],
                exclude_patterns=exclude_patterns,
            )
            if reject_reason:
                return ScrapedContent(
                    url=canonical_url,
                    title="",
                    content="",
                    html="",
                    word_count=0,
                    success=False,
                    error=reject_reason,
                )

            title = (
                self._select_attr_or_text(soup, selectors.get("title"))
                or self._json_ld_value(soup, ["headline"])
            )
            author = (
                self._select_text(soup, selectors.get("author"))
                or self._json_ld_value(soup, ["author"])
            )
            published_at = self._parse_date(
                self._select_attr_or_text(soup, selectors.get("date"))
                or self._meta_content(soup, [
                    "article:published_time",
                    "datePublished",
                    "pubdate",
                    "publishdate",
                ])
                or self._json_ld_value(soup, ["datePublished", "dateCreated"])
            )
            image_url = (
                self._select_attr_or_text(soup, selectors.get("image"))
                or self._meta_content(soup, ["og:image", "twitter:image"])
                or self._json_ld_value(soup, ["image", "thumbnailUrl"])
            )
            if image_url:
                image_url = urljoin(url, image_url)

            body_html = self._select_html(soup, selectors.get("body"))
            if body_html:
                content = self._html_to_text(body_html)
                clean_html = body_html
            else:
                clean_html, fallback_title = self._readability_fallback(html, soup)
                title = title or fallback_title
                content = self._html_to_text(clean_html)

            title = title or self._meta_content(soup, ["og:title", "twitter:title"]) or ""
            title = " ".join(title.split())
            content = self._normalize_extracted_text(content)
            word_count = len(content.split())

            quality_error = self._content_quality_error(
                title=title,
                content=content,
                canonical_url=canonical_url,
                published_at=published_at,
                min_word_count=scraper_config.get("min_word_count", 30),
                min_unique_words=scraper_config.get("min_unique_words", 25),
                bad_title_patterns=[
                    re.compile(pattern, re.IGNORECASE)
                    for pattern in scraper_config.get("bad_title_patterns", [])
                ],
                bad_content_patterns=[
                    re.compile(pattern, re.IGNORECASE)
                    for pattern in scraper_config.get("bad_content_patterns", [])
                ],
            )
            if quality_error:
                return ScrapedContent(
                    url=canonical_url,
                    title=title,
                    content=content,
                    html=clean_html,
                    word_count=word_count,
                    success=False,
                    author=author,
                    published_at=published_at,
                    image_url=image_url,
                    error=quality_error,
                )

            if not title or word_count < scraper_config.get("min_word_count", 30):
                return ScrapedContent(
                    url=url,
                    title=title,
                    content=content,
                    html=clean_html,
                    word_count=word_count,
                    success=False,
                    author=author,
                    published_at=published_at,
                    image_url=image_url,
                    error="low_content_or_missing_title",
                )

            return ScrapedContent(
                url=canonical_url,
                title=title,
                content=content,
                html=clean_html,
                word_count=word_count,
                success=True,
                author=author,
                published_at=published_at,
                image_url=image_url,
            )

        except Exception as e:
            logger.error("scrape_parse_error", url=url, error=str(e))
            return ScrapedContent(
                url=url, title="", content="", html="",
                word_count=0, success=False, error=str(e),
            )

    def scrape_batch(
        self, urls: list[str], max_failures: int = 5
    ) -> list[ScrapedContent]:
        """Scrape multiple URLs with failure tracking."""
        results = []
        failures = 0
        for url in urls:
            if failures >= max_failures:
                break
            result = self.scrape_article(url)
            results.append(result)
            if not result.success:
                failures += 1
        return results

    @staticmethod
    def _url_reject_reason(
        url: str,
        source_domain: str = "",
        include_patterns: Optional[list[re.Pattern]] = None,
        exclude_patterns: Optional[list[re.Pattern]] = None,
    ) -> Optional[str]:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            return "invalid_scheme"
        if source_domain and parsed.netloc.replace("www.", "") != source_domain:
            return "external_domain"
        if include_patterns and not any(pattern.search(url) for pattern in include_patterns):
            return "not_in_include_patterns"
        if any(pattern.search(url) for pattern in (exclude_patterns or DEFAULT_EXCLUDE_PATTERNS)):
            return "excluded_url_pattern"
        path_parts = [part for part in parsed.path.strip("/").split("/") if part]
        if not path_parts:
            return "homepage"
        if len(path_parts) == 1 and ArticleScraper._looks_like_section_slug(path_parts[0]):
            return "section_page"
        if len(path_parts) == 2 and path_parts[0] in {"index.php", "category", "kategorija"}:
            return "section_page"
        return None

    @staticmethod
    def _looks_like_section_slug(slug: str) -> bool:
        normalized = slug.lower().strip("/")
        section_slugs = {
            "vesti", "mk", "sport", "kultura", "ekonomija", "makedonija",
            "svet", "region", "magazin", "scena", "tehnologija", "resursi",
            "studio", "soopstenija", "crna-hronika", "najnovi-vesti",
            "live-tv", "archive", "arhiva", "sdk-magazin",
        }
        return normalized in section_slugs

    @staticmethod
    def _content_quality_error(
        title: str,
        content: str,
        canonical_url: str,
        published_at: Optional[datetime.datetime],
        min_word_count: int,
        min_unique_words: int,
        bad_title_patterns: Optional[list[re.Pattern]] = None,
        bad_content_patterns: Optional[list[re.Pattern]] = None,
    ) -> Optional[str]:
        if not title:
            return "missing_title"
        if len(content.split()) < min_word_count:
            return "low_word_count"
        if any(pattern.search(title) for pattern in DEFAULT_BAD_TITLE_PATTERNS):
            return "bad_title_pattern"
        if any(pattern.search(title) for pattern in (bad_title_patterns or [])):
            return "bad_title_pattern"
        if any(pattern.search(content) for pattern in DEFAULT_BAD_CONTENT_PATTERNS):
            return "bad_content_pattern"
        if any(pattern.search(content) for pattern in (bad_content_patterns or [])):
            return "bad_content_pattern"
        parsed = urlparse(canonical_url)
        path_parts = [part for part in parsed.path.strip("/").split("/") if part]
        if not published_at and len(path_parts) <= 2:
            lowered = title.lower()
            if ArticleScraper._looks_like_section_slug(path_parts[-1] if path_parts else ""):
                return "undated_section_page"
            if lowered in {"home", "homepage", "почетна"}:
                return "homepage_title"
        unique_words = {word.lower() for word in re.findall(r"\w+", content) if len(word) > 2}
        if len(unique_words) < min_unique_words:
            return "low_unique_word_count"
        return None

    def _fetch_text(self, url: str) -> Optional[str]:
        self._rate_limit()
        try:
            response = self.client.get(url)
            response.raise_for_status()
            return response.text
        except httpx.HTTPError as e:
            if self.allow_insecure_ssl_fallback and "CERTIFICATE_VERIFY_FAILED" in str(e):
                return self._fetch_text_insecure(url, str(e))
            logger.warning("scrape_fetch_failed", url=url, error=str(e))
            return None

    def _fetch_text_insecure(self, url: str, original_error: str) -> Optional[str]:
        logger.warning(
            "scrape_ssl_verify_failed_retrying_insecure",
            url=url,
            error=original_error,
        )
        try:
            with httpx.Client(
                timeout=30.0,
                follow_redirects=True,
                verify=False,
                headers=self.client.headers,
            ) as client:
                response = client.get(url)
                response.raise_for_status()
                return response.text
        except httpx.HTTPError as e:
            logger.warning("scrape_fetch_failed", url=url, error=str(e))
            return None

    @staticmethod
    def _select_text(soup: BeautifulSoup, selector: Optional[str]) -> Optional[str]:
        if not selector:
            return None
        element = soup.select_one(selector)
        if not element:
            return None
        return element.get_text(" ", strip=True)

    @staticmethod
    def _select_html(soup: BeautifulSoup, selector: Optional[str]) -> Optional[str]:
        if not selector:
            return None
        # Body selectors are ordered from source-specific to broad fallback.
        # Evaluating a comma-separated selector in one call returns the first
        # matching DOM node, which can make an outer <article> win over a later
        # .entry-content selector and pull sidebars/recommendations into NLP.
        candidates = [part.strip() for part in selector.split(",") if part.strip()]
        broad_fallbacks = {"article", "main", "body"}
        candidates.sort(key=lambda candidate: candidate.lower() in broad_fallbacks)
        for candidate in candidates:
            if not candidate:
                continue
            element = soup.select_one(candidate)
            if element:
                return str(element)
        return None

    @staticmethod
    def _select_attr_or_text(soup: BeautifulSoup, selector: Optional[str]) -> Optional[str]:
        if not selector:
            return None
        element = soup.select_one(selector)
        if not element:
            return None
        for attr in ("datetime", "content", "src", "href"):
            value = element.get(attr)
            if value:
                return value.strip()
        return element.get_text(" ", strip=True)

    @staticmethod
    def _meta_content(soup: BeautifulSoup, names: list[str]) -> Optional[str]:
        for name in names:
            element = (
                soup.find("meta", attrs={"property": name})
                or soup.find("meta", attrs={"name": name})
                or soup.find("meta", attrs={"itemprop": name})
            )
            if element and element.get("content"):
                return element["content"].strip()
        return None

    @staticmethod
    def _json_ld_value(soup: BeautifulSoup, names: list[str]) -> Optional[str]:
        """Read a scalar value from nested schema.org JSON-LD blocks."""
        for script in soup.select("script[type='application/ld+json']"):
            raw = script.string or script.get_text(" ", strip=True)
            if not raw:
                continue
            try:
                data = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                continue

            stack = [data]
            while stack:
                current = stack.pop()
                if isinstance(current, dict):
                    for name in names:
                        if name in current:
                            value = ArticleScraper._json_ld_scalar(current[name])
                            if value:
                                return value
                    stack.extend(current.values())
                elif isinstance(current, list):
                    stack.extend(current)
        return None

    @staticmethod
    def _json_ld_scalar(value) -> Optional[str]:
        if isinstance(value, str):
            return value.strip() or None
        if isinstance(value, dict):
            for key in ("name", "url", "contentUrl", "@id"):
                nested = value.get(key)
                if isinstance(nested, str) and nested.strip():
                    return nested.strip()
        if isinstance(value, list):
            for item in value:
                nested = ArticleScraper._json_ld_scalar(item)
                if nested:
                    return nested
        return None

    @staticmethod
    def _canonical_url(soup: BeautifulSoup, fallback_url: str) -> str:
        canonical = soup.find("link", rel=lambda value: value and "canonical" in value)
        if canonical and canonical.get("href"):
            return normalize_url(urljoin(fallback_url, canonical["href"]))
        og_url = (
            soup.find("meta", attrs={"property": "og:url"})
            or soup.find("meta", attrs={"name": "og:url"})
        )
        if og_url and og_url.get("content"):
            return normalize_url(urljoin(fallback_url, og_url["content"]))
        return normalize_url(fallback_url)

    @staticmethod
    def _html_to_text(html: str) -> str:
        soup = BeautifulSoup(html, "lxml")
        for element in soup(["script", "style", "iframe", "nav", "form"]):
            element.decompose()
        for selector in CONTENT_NOISE_SELECTORS:
            for element in soup.select(selector):
                element.decompose()
        return soup.get_text(separator="\n", strip=True)

    @staticmethod
    def _normalize_extracted_text(text: str) -> str:
        lines = []
        for raw_line in text.splitlines():
            line = " ".join(raw_line.split())
            if line and (not lines or line != lines[-1]):
                lines.append(line)
        return "\n".join(lines)

    @staticmethod
    def _readability_fallback(html: str, soup: BeautifulSoup) -> tuple[str, str]:
        try:
            from readability import Document

            doc = Document(html)
            return doc.summary(), doc.title()
        except Exception:
            article = soup.select_one("article, main, .entry-content, .post-content")
            if article:
                return str(article), ""
            body = soup.body or soup
            return str(body), ""

    @staticmethod
    def _parse_date(raw: Optional[str]) -> Optional[datetime.datetime]:
        if not raw:
            return None
        value = " ".join(raw.replace("|", " ").split())
        dotted_date = re.search(
            r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})"
            r"(?:\D+(\d{1,2}):(\d{2}))?",
            value,
        )
        if dotted_date:
            day, month, year, hour, minute = dotted_date.groups()
            try:
                return datetime.datetime(
                    int(year),
                    int(month),
                    int(day),
                    int(hour or 0),
                    int(minute or 0),
                )
            except ValueError:
                return None
        try:
            return dateparser.parse(value)
        except (ValueError, TypeError, OverflowError):
            return None

    def _rate_limit(self):
        now = time.time()
        elapsed = now - self._last_request_time
        if elapsed < self.delay:
            time.sleep(self.delay - elapsed)
        self._last_request_time = time.time()

    def close(self):
        self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
