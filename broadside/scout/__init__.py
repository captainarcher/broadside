"""Scout pipeline: news sourcing, dedup, filtering, ranking, and digest."""

from __future__ import annotations

import logging

from broadside.config import BroadsideConfig
from broadside.scout.dedup import deduplicate
from broadside.scout.digest import format_digest, save_digest
from broadside.scout.filter import filter_stories
from broadside.scout.ranker import rank_stories
from broadside.scout.sources import Story, fetch_all_sources

logger = logging.getLogger(__name__)

__all__ = [
    "Story",
    "run_scout_pipeline",
    "fetch_all_sources",
    "deduplicate",
    "filter_stories",
    "rank_stories",
    "save_digest",
    "format_digest",
]


def run_scout_pipeline(config: BroadsideConfig) -> list[Story]:
    """Run the full scout pipeline: fetch -> dedup -> filter -> rank -> digest.

    Args:
        config: Broadside configuration containing news source settings
                and political filter settings.

    Returns:
        Ranked list of Story objects after dedup, filtering, and scoring.
    """
    news = config.news

    # 1. Fetch from all sources
    logger.info("Fetching stories from all sources...")
    raw_stories = fetch_all_sources(news.sources)
    logger.info("Fetched %d raw stories", len(raw_stories))

    # 2. Deduplicate
    logger.info("Deduplicating...")
    unique_stories = deduplicate(raw_stories)
    logger.info("After dedup: %d stories", len(unique_stories))

    # 3. Filter political content
    logger.info("Filtering political content...")
    filtered_stories = filter_stories(
        unique_stories,
        keywords_file=news.political_filter.keywords_file,
        use_llm=news.political_filter.llm_classification,
    )
    logger.info("After filtering: %d stories", len(filtered_stories))

    # 4. Rank by satire potential
    logger.info("Ranking by satire potential...")
    ranked_stories = rank_stories(filtered_stories)

    # 5. Save digest
    logger.info("Saving digest...")
    save_digest(ranked_stories)
    digest_text = format_digest(ranked_stories)
    logger.info("Digest:\n%s", digest_text)

    return ranked_stories
