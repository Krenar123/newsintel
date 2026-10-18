"""Dedicated TIME.mk aggregator parser.

TIME.mk is useful as a spread signal, but it should not be treated as an
original news source. This parser extracts story clusters and source mentions
without normalizing TIME pages into articles.
"""

from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from src.ingestion.rss_fetcher import _certifi_verify


@dataclass
class TimeMkArticleRef:
    """One article reference inside a TIME.mk story cluster."""
    title: str
    url: str
    source_name: Optional[str] = None
    source_slug: Optional[str] = None


@dataclass
class TimeMkStory:
    """Aggregator story cluster from TIME.mk."""
    cluster_id: str
    title: str
    story_url: Optional[str] = None
    summary_url: Optional[str] = None
    related_topics_url: Optional[str] = None
    reported_count: Optional[int] = None
    articles: list[TimeMkArticleRef] = field(default_factory=list)

    @property
    def source_names(self) -> list[str]:
        names = []
        seen = set()
        for article in self.articles:
            if article.source_name and article.source_name not in seen:
                seen.add(article.source_name)
                names.append(article.source_name)
        return names

    @property
    def source_count(self) -> int:
        return len(self.source_names)


class TimeMkAggregator:
    """Fetch and parse TIME.mk story-spread clusters."""

    def __init__(self, base_url: str = "https://time.mk", timeout: float = 20.0):
        self.base_url = base_url.rstrip("/")
        self.client = httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            verify=_certifi_verify(),
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; NewsIntel/1.0)",
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "mk,en-US;q=0.9,en;q=0.8",
            },
        )

    def fetch_front_page(self, path: str = "/") -> list[TimeMkStory]:
        html = self._fetch(path)
        return self.parse(html)

    def parse(self, html: str) -> list[TimeMkStory]:
        soup = BeautifulSoup(html, "lxml")
        stories: dict[str, TimeMkStory] = {}
        last_article_by_cluster: dict[str, TimeMkArticleRef] = {}

        for link in soup.select("a[href]"):
            href = link.get("href") or ""
            text = " ".join(link.get_text(" ", strip=True).split())
            if not href or not text:
                continue
            normalized = self._normalize_href(href)
            parsed = urlparse(normalized)
            path_parts = [part for part in parsed.path.strip("/").split("/") if part]
            if not path_parts:
                continue

            kind = path_parts[0]
            if kind == "r" and len(path_parts) >= 3:
                cluster_id = path_parts[1]
                story = stories.setdefault(cluster_id, TimeMkStory(cluster_id=cluster_id, title=text))
                article = TimeMkArticleRef(title=text, url=normalized)
                story.articles.append(article)
                last_article_by_cluster[cluster_id] = article
                if not story.title or story.title == cluster_id:
                    story.title = text
            elif kind == "s" and len(path_parts) >= 2:
                source_slug = path_parts[1]
                cluster_id = self._nearest_cluster(last_article_by_cluster)
                if cluster_id:
                    article = last_article_by_cluster.get(cluster_id)
                    if article and not article.source_name:
                        article.source_name = text
                        article.source_slug = source_slug
            elif kind == "c" and len(path_parts) >= 2:
                cluster_id = path_parts[1]
                story = stories.setdefault(cluster_id, TimeMkStory(cluster_id=cluster_id, title=text))
                story.story_url = normalized
                count = self._extract_count(text)
                if count is not None:
                    story.reported_count = count
            elif kind == "sc" and len(path_parts) >= 2:
                cluster_id = path_parts[1]
                story = stories.setdefault(cluster_id, TimeMkStory(cluster_id=cluster_id, title=text))
                story.related_topics_url = normalized
            elif kind == "ai" and len(path_parts) >= 2:
                cluster_id = path_parts[1]
                story = stories.setdefault(cluster_id, TimeMkStory(cluster_id=cluster_id, title=text))
                story.summary_url = normalized

        return [
            story for story in stories.values()
            if story.articles or story.story_url or story.reported_count
        ]

    def close(self) -> None:
        self.client.close()

    def _fetch(self, path: str) -> str:
        url = self._normalize_href(path)
        try:
            response = self.client.get(url)
            response.raise_for_status()
            return response.text
        except httpx.HTTPError:
            with httpx.Client(
                timeout=self.client.timeout,
                follow_redirects=True,
                verify=False,
                headers=self.client.headers,
            ) as insecure_client:
                response = insecure_client.get(url)
                response.raise_for_status()
                return response.text

    def _normalize_href(self, href: str) -> str:
        return urljoin(f"{self.base_url}/", href)

    @staticmethod
    def _extract_count(text: str) -> Optional[int]:
        digits = "".join(char for char in text if char.isdigit())
        return int(digits) if digits else None

    @staticmethod
    def _nearest_cluster(last_article_by_cluster: dict[str, TimeMkArticleRef]) -> Optional[str]:
        if not last_article_by_cluster:
            return None
        return next(reversed(last_article_by_cluster))
