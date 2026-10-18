"""
Facebook Page ingestion through the Meta Graph API.

This module treats public Page posts as RawArticle records so the existing
pipeline can summarize, categorize, extract entities, and deduplicate them.
It intentionally uses official Graph API access only.
"""

import datetime
import time
from typing import Optional

import httpx
from dateutil import parser as dateparser
import structlog

from src.ingestion.rss_fetcher import RawArticle

logger = structlog.get_logger()


class FacebookPageFetcher:
    """Fetch public posts from configured Facebook Pages."""

    def __init__(
        self,
        access_token: Optional[str] = None,
        api_version: str = "v24.0",
        http_client: Optional[httpx.Client] = None,
        delay_seconds: float = 1.0,
        max_posts_per_page: int = 25,
    ):
        self.access_token = access_token
        self.api_version = api_version
        self.delay = delay_seconds
        self.max_posts_per_page = max_posts_per_page
        self.client = http_client or httpx.Client(
            timeout=30.0,
            follow_redirects=True,
            headers={
                "User-Agent": (
                    "NewsIntel/1.0 (Facebook Page monitor; "
                    "+https://github.com/newsintel)"
                )
            },
        )

    def fetch_all_pages(self, country_config: dict) -> list[RawArticle]:
        """Fetch every enabled Facebook Page configured for a country."""
        pages = country_config.get("facebook_pages", [])
        articles: list[RawArticle] = []

        if not pages:
            return articles

        if not self.access_token:
            logger.warning(
                "facebook_skipped_missing_token",
                page_count=len(pages),
            )
            return articles

        country_code = country_config.get("code", "")
        for page_config in pages:
            if page_config.get("enabled", True) is False:
                continue

            page_articles = self.fetch_page(page_config, country_code=country_code)
            articles.extend(page_articles)

            if self.delay > 0:
                time.sleep(self.delay)

        return articles

    def fetch_page(
        self,
        page_config: dict,
        country_code: str = "",
    ) -> list[RawArticle]:
        """Fetch posts for one Facebook Page config."""
        page_ref = (
            page_config.get("page_id")
            or page_config.get("page_handle")
            or page_config.get("id")
        )
        if not page_ref:
            logger.warning("facebook_page_missing_identifier", page=page_config)
            return []

        fields = ",".join(
            [
                "id",
                "message",
                "story",
                "created_time",
                "permalink_url",
                "full_picture",
                "from",
                "attachments{media,url,title,description}",
            ]
        )
        url = f"https://graph.facebook.com/{self.api_version}/{page_ref}/posts"
        params = {
            "fields": fields,
            "limit": min(self.max_posts_per_page, page_config.get("limit", self.max_posts_per_page)),
            "access_token": self.access_token,
        }

        logger.info("fetching_facebook_page", page=page_config.get("name", page_ref))

        try:
            response = self.client.get(url, params=params)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.error(
                "facebook_fetch_failed",
                page=page_config.get("name", page_ref),
                status_code=exc.response.status_code,
                error=exc.response.text[:500],
            )
            return []
        except httpx.HTTPError as exc:
            logger.error(
                "facebook_fetch_failed",
                page=page_config.get("name", page_ref),
                error=str(exc),
            )
            return []

        payload = response.json()
        fetched_at = datetime.datetime.utcnow()
        return [
            article
            for post in payload.get("data", [])
            if (article := self._post_to_article(post, page_config, country_code, fetched_at))
        ]

    def _post_to_article(
        self,
        post: dict,
        page_config: dict,
        country_code: str,
        fetched_at: datetime.datetime,
    ) -> Optional[RawArticle]:
        text = (post.get("message") or post.get("story") or "").strip()
        if not text:
            return None

        post_id = post.get("id", "")
        created_at = self._parse_date(post.get("created_time"))
        page_name = page_config.get("name") or post.get("from", {}).get("name") or "Facebook Page"
        page_url = page_config.get("url") or "https://www.facebook.com"
        permalink = post.get("permalink_url") or f"{page_url.rstrip('/')}/posts/{post_id}"
        title = self._title_from_text(text, page_name)

        article = RawArticle(
            url=permalink,
            title=title,
            content=text,
            author=post.get("from", {}).get("name") or page_name,
            published_at=created_at,
            fetched_at=fetched_at,
            language=page_config.get("language", "mk"),
            source_name=page_name,
            source_url=page_url,
            source_country_code=country_code,
            source_type=page_config.get("source_type", "social_media"),
            source_reliability_score=page_config.get("reliability_score", 0.6),
            source_political_leaning=page_config.get("political_leaning", "unknown"),
            source_ownership=page_config.get("ownership"),
            image_url=post.get("full_picture") or self._attachment_image(post),
            raw_html=None,
            ingestion_method="facebook",
            platform="facebook",
            external_id=post_id,
            platform_account_id=post.get("from", {}).get("id") or page_config.get("page_id"),
            platform_account_name=page_name,
        )
        article.compute_hash()
        return article

    @staticmethod
    def _title_from_text(text: str, page_name: str) -> str:
        first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
        title = first_line[:120].strip()
        if len(first_line) > 120:
            title = f"{title.rstrip()}..."
        return title or f"Facebook post by {page_name}"

    @staticmethod
    def _attachment_image(post: dict) -> Optional[str]:
        attachments = post.get("attachments", {}).get("data", [])
        for attachment in attachments:
            media = attachment.get("media", {})
            image = media.get("image", {})
            if image.get("src"):
                return image["src"]
        return None

    @staticmethod
    def _parse_date(raw: Optional[str]) -> Optional[datetime.datetime]:
        if not raw:
            return None
        try:
            return dateparser.parse(raw)
        except (TypeError, ValueError):
            return None

    def close(self):
        self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
