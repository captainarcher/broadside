"""Deduplication of stories by URL normalization and title similarity."""

from __future__ import annotations

import logging
from urllib.parse import urlparse, urlunparse

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from broadside.scout.sources import Story

logger = logging.getLogger(__name__)

SIMILARITY_THRESHOLD = 0.85


def normalize_url(url: str) -> str:
    """Normalize a URL for dedup comparison.

    Strips query parameters, fragments, trailing slashes, and lowercases.
    """
    parsed = urlparse(url)
    # Rebuild without query and fragment
    normalized = urlunparse(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            parsed.path.rstrip("/"),
            "",  # params
            "",  # query
            "",  # fragment
        )
    )
    return normalized


def _merge_stories(primary: Story, duplicate: Story) -> Story:
    """Merge two duplicate stories, keeping the best metadata."""
    # Keep whichever has a longer summary
    summary = primary.summary if len(primary.summary) >= len(duplicate.summary) else duplicate.summary
    # Sum popularity scores
    popularity = primary.popularity_score + duplicate.popularity_score
    # Merge raw metadata
    merged_meta = {**duplicate.raw_metadata, **primary.raw_metadata}
    merged_meta["merged_sources"] = merged_meta.get("merged_sources", []) + [
        duplicate.source
    ]

    return Story(
        title=primary.title,
        url=primary.url,
        source=primary.source,
        category=primary.category or duplicate.category,
        summary=summary,
        published_at=primary.published_at or duplicate.published_at,
        popularity_score=popularity,
        raw_metadata=merged_meta,
    )


def deduplicate(stories: list[Story]) -> list[Story]:
    """Remove duplicate stories by URL normalization and title similarity.

    1. Exact URL dedup (after normalization).
    2. TF-IDF cosine similarity on titles -- merge pairs above threshold.
    """
    if not stories:
        return []

    # --- Phase 1: URL dedup ---
    url_map: dict[str, Story] = {}
    for story in stories:
        norm = normalize_url(story.url)
        if norm in url_map:
            url_map[norm] = _merge_stories(url_map[norm], story)
        else:
            url_map[norm] = story

    unique_stories = list(url_map.values())
    logger.info(
        "URL dedup: %d -> %d stories", len(stories), len(unique_stories)
    )

    if len(unique_stories) <= 1:
        return unique_stories

    # --- Phase 2: Title similarity dedup ---
    titles = [s.title for s in unique_stories]
    vectorizer = TfidfVectorizer(stop_words="english")
    tfidf_matrix = vectorizer.fit_transform(titles)
    sim_matrix = cosine_similarity(tfidf_matrix)

    # Mark stories to merge (keep lower index as primary)
    merged_into: dict[int, int] = {}  # duplicate_idx -> primary_idx
    for i in range(len(unique_stories)):
        if i in merged_into:
            continue
        for j in range(i + 1, len(unique_stories)):
            if j in merged_into:
                continue
            if sim_matrix[i, j] >= SIMILARITY_THRESHOLD:
                merged_into[j] = i

    # Apply merges
    for dup_idx, primary_idx in merged_into.items():
        unique_stories[primary_idx] = _merge_stories(
            unique_stories[primary_idx], unique_stories[dup_idx]
        )

    result = [
        s for idx, s in enumerate(unique_stories) if idx not in merged_into
    ]
    logger.info(
        "Title dedup: %d -> %d stories", len(unique_stories), len(result)
    )

    return result
