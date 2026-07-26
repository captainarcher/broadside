"""Fetchers for all news sources used by the scout pipeline."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import feedparser
import httpx

from broadside.config import (
    GoogleNewsSourceConfig,
    HackerNewsSourceConfig,
    NewsDataSourceConfig,
    NewsSourcesConfig,
    RedditSourceConfig,
)

logger = logging.getLogger(__name__)


@dataclass
class Story:
    """Common story representation across all news sources."""

    title: str
    url: str
    source: str
    category: str = ""
    summary: str = ""
    published_at: str = ""
    popularity_score: float = 0.0
    raw_metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Reddit (via public RSS — no API credentials needed)
# ---------------------------------------------------------------------------

class RedditFetcher:
    """Fetch stories from configured subreddits via public RSS feeds.

    Reddit killed self-service API key creation in Nov 2025. Public RSS
    feeds at reddit.com/r/<sub>/.rss still work without auth and return
    the top ~25 posts per subreddit.
    """

    def __init__(self, config: RedditSourceConfig) -> None:
        self.config = config

    def fetch(self) -> list[Story]:
        stories: list[Story] = []
        for sub_name in self.config.subreddits:
            try:
                url = f"https://www.reddit.com/r/{sub_name}/.rss"
                feed = feedparser.parse(url)
                for entry in feed.entries:
                    link = entry.get("link", "")
                    title = entry.get("title", "")
                    if not title or not link:
                        continue
                    # Reddit RSS entries link to the reddit post; extract
                    # the external URL from the content if present
                    external_url = link
                    content = entry.get("content", [{}])
                    if content and isinstance(content, list):
                        html = content[0].get("value", "")
                        # Look for [link] href pointing outside reddit
                        import re
                        ext_match = re.search(
                            r'<a href="(https?://(?!www\.reddit\.com)[^"]+)">\[link\]</a>',
                            html,
                        )
                        if ext_match:
                            external_url = ext_match.group(1)

                    published = entry.get("published", entry.get("updated", ""))
                    stories.append(
                        Story(
                            title=title,
                            url=external_url,
                            source=f"reddit/r/{sub_name}",
                            category=sub_name,
                            summary=entry.get("summary", "")[:300],
                            published_at=published,
                            popularity_score=0.0,
                            raw_metadata={
                                "subreddit": sub_name,
                                "reddit_link": link,
                                "author": entry.get("author", ""),
                            },
                        )
                    )
            except Exception:
                logger.exception("Failed to fetch r/%s RSS", sub_name)

        return stories


# ---------------------------------------------------------------------------
# Hacker News
# ---------------------------------------------------------------------------

_HN_BASE = "https://hacker-news.firebaseio.com/v0"


class HackerNewsFetcher:
    """Fetch top stories from Hacker News via Firebase API."""

    def __init__(self, config: HackerNewsSourceConfig) -> None:
        self.config = config

    def fetch(self) -> list[Story]:
        stories: list[Story] = []
        try:
            with httpx.Client(timeout=30) as client:
                resp = client.get(f"{_HN_BASE}/topstories.json")
                resp.raise_for_status()
                story_ids: list[int] = resp.json()[: self.config.top_n]

                for sid in story_ids:
                    try:
                        item_resp = client.get(f"{_HN_BASE}/item/{sid}.json")
                        item_resp.raise_for_status()
                        item = item_resp.json()
                        if item is None or item.get("type") != "story":
                            continue
                        url = item.get("url", "")
                        if not url:
                            continue
                        created = datetime.fromtimestamp(
                            item.get("time", 0), tz=timezone.utc
                        )
                        stories.append(
                            Story(
                                title=item.get("title", ""),
                                url=url,
                                source="hackernews",
                                category="tech",
                                summary="",
                                published_at=created.isoformat(),
                                popularity_score=float(item.get("score", 0)),
                                raw_metadata={
                                    "hn_id": sid,
                                    "by": item.get("by", ""),
                                    "descendants": item.get("descendants", 0),
                                },
                            )
                        )
                    except Exception:
                        logger.debug("Failed to fetch HN item %s", sid)
        except Exception:
            logger.exception("Failed to fetch Hacker News top stories")

        return stories


# ---------------------------------------------------------------------------
# Google News (RSS)
# ---------------------------------------------------------------------------

_GOOGLE_NEWS_TOPIC_URLS: dict[str, str] = {
    "technology": "https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRGRqTVhZU0FtVnVHZ0pWVXlnQVAB",
    "business": "https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRGx6TVdZU0FtVnVHZ0pWVXlnQVAB",
    "science": "https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRFp0Y1RjU0FtVnVHZ0pWVXlnQVAB",
    "entertainment": "https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNREpxYW5RU0FtVnVHZ0pWVXlnQVAB",
}


class GoogleNewsFetcher:
    """Fetch stories from Google News RSS feeds for configured topics."""

    def __init__(self, config: GoogleNewsSourceConfig) -> None:
        self.config = config

    def fetch(self) -> list[Story]:
        stories: list[Story] = []
        for topic in self.config.topics:
            url = _GOOGLE_NEWS_TOPIC_URLS.get(topic)
            if not url:
                logger.warning("No Google News RSS URL for topic: %s", topic)
                continue
            try:
                feed = feedparser.parse(url)
                for entry in feed.entries:
                    published = entry.get("published", "")
                    stories.append(
                        Story(
                            title=entry.get("title", ""),
                            url=entry.get("link", ""),
                            source="google_news",
                            category=topic,
                            summary=entry.get("summary", ""),
                            published_at=published,
                            popularity_score=0.0,
                            raw_metadata={
                                "topic": topic,
                                "source_title": entry.get("source", {}).get(
                                    "title", ""
                                )
                                if isinstance(entry.get("source"), dict)
                                else "",
                            },
                        )
                    )
            except Exception:
                logger.exception("Failed to fetch Google News topic: %s", topic)

        return stories


# ---------------------------------------------------------------------------
# NewsData.io
# ---------------------------------------------------------------------------

_NEWSDATA_URL = "https://newsdata.io/api/1/news"


class NewsDataFetcher:
    """Fetch stories from the NewsData.io REST API."""

    def __init__(self, config: NewsDataSourceConfig) -> None:
        self.config = config

    def fetch(self) -> list[Story]:
        api_key = os.environ.get("NEWSDATA_API_KEY", "")
        if not api_key:
            logger.warning("NEWSDATA_API_KEY not set; skipping NewsDataFetcher")
            return []

        stories: list[Story] = []
        try:
            with httpx.Client(timeout=30) as client:
                resp = client.get(
                    _NEWSDATA_URL,
                    params={
                        "apikey": api_key,
                        "category": ",".join(self.config.categories),
                        "language": "en",
                    },
                )
                resp.raise_for_status()
                data = resp.json()

                for article in data.get("results", []):
                    stories.append(
                        Story(
                            title=article.get("title", ""),
                            url=article.get("link", ""),
                            source="newsdata",
                            category=",".join(article.get("category", [])),
                            summary=article.get("description", "") or "",
                            published_at=article.get("pubDate", ""),
                            popularity_score=0.0,
                            raw_metadata={
                                "source_id": article.get("source_id", ""),
                                "creator": article.get("creator", []),
                                "country": article.get("country", []),
                                "keywords": article.get("keywords", []),
                            },
                        )
                    )
        except Exception:
            logger.exception("Failed to fetch from NewsData.io")

        return stories


# ---------------------------------------------------------------------------
# Supplementary RSS feeds
# ---------------------------------------------------------------------------

_SUPPLEMENTARY_FEEDS: dict[str, str] = {
    "upi_odd": "https://rss.upi.com/news/odd_news/rss",
    "ars_technica": "https://feeds.arstechnica.com/arstechnica/index",
    "the_verge": "https://www.theverge.com/rss/index.xml",
}


class SupplementaryFetcher:
    """Fetch stories from supplementary RSS feeds (UPI Odd News, Ars Technica, The Verge)."""

    def fetch(self) -> list[Story]:
        stories: list[Story] = []
        for name, url in _SUPPLEMENTARY_FEEDS.items():
            try:
                feed = feedparser.parse(url)
                for entry in feed.entries:
                    published = entry.get("published", "")
                    stories.append(
                        Story(
                            title=entry.get("title", ""),
                            url=entry.get("link", ""),
                            source=name,
                            category=name,
                            summary=entry.get("summary", ""),
                            published_at=published,
                            popularity_score=0.0,
                            raw_metadata={"feed": name},
                        )
                    )
            except Exception:
                logger.exception("Failed to fetch supplementary feed: %s", name)

        return stories


# ---------------------------------------------------------------------------
# Aggregate helper
# ---------------------------------------------------------------------------


def fetch_all_sources(sources_config: NewsSourcesConfig) -> list[Story]:
    """Run every fetcher and return a combined list of stories."""
    all_stories: list[Story] = []

    fetchers: list[tuple[str, Any]] = [
        ("Reddit", RedditFetcher(sources_config.reddit)),
        ("HackerNews", HackerNewsFetcher(sources_config.hackernews)),
        ("GoogleNews", GoogleNewsFetcher(sources_config.google_news)),
        ("NewsData", NewsDataFetcher(sources_config.newsdata)),
        ("Supplementary", SupplementaryFetcher()),
    ]

    for name, fetcher in fetchers:
        try:
            stories = fetcher.fetch()
            logger.info("%s: fetched %d stories", name, len(stories))
            all_stories.extend(stories)
        except Exception:
            logger.exception("Fetcher %s failed entirely", name)

    return all_stories
