"""Political content filter with keyword blocklist and LLM classification."""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path

from broadside.llm import chat
from broadside.scout.sources import Story

logger = logging.getLogger(__name__)

_BATCH_SIZE = 20


def _load_keywords(keywords_file: str) -> list[str]:
    """Load political keywords from a text file (one keyword per line)."""
    path = Path(keywords_file)
    if not path.exists():
        logger.warning("Keywords file not found: %s", keywords_file)
        return []
    lines = path.read_text().strip().splitlines()
    return [line.strip().lower() for line in lines if line.strip() and not line.startswith("#")]


def _keyword_match(text: str, keywords: list[str]) -> bool:
    """Check if text matches any keyword using word-boundary matching (case-insensitive)."""
    text_lower = text.lower()
    for kw in keywords:
        pattern = rf"\b{re.escape(kw)}\b"
        if re.search(pattern, text_lower):
            return True
    return False


def _llm_classify_batch(
    stories: list[Story],
) -> list[bool]:
    """Use Claude Haiku to classify whether stories are primarily about politics.

    Returns a list of booleans: True means the story IS political (should be filtered).
    """
    headlines_text = "\n".join(
        f"{i + 1}. {s.title}" for i, s in enumerate(stories)
    )

    prompt = (
        "You are a content classifier. For each headline below, determine if it is "
        "PRIMARILY about partisan politics, elections, political parties, or government "
        "policy debates. Respond with ONLY a numbered list of YES or NO.\n\n"
        f"Headlines:\n{headlines_text}\n\n"
        "Respond with one YES or NO per line, numbered to match:"
    )

    try:
        text = chat(
            model="anthropic/claude-haiku-4.5",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1024,
        )
        results: list[bool] = []
        for line in text.strip().splitlines():
            line_clean = line.strip().upper()
            # Extract YES/NO from lines like "1. YES" or "1: NO"
            results.append("YES" in line_clean)

        # Pad or truncate to match input length
        while len(results) < len(stories):
            results.append(False)
        return results[: len(stories)]
    except Exception:
        logger.exception("LLM classification failed")
        return [False] * len(stories)


def filter_stories(
    stories: list[Story],
    keywords_file: str = "config/political-keywords.txt",
    use_llm: bool = True,
) -> list[Story]:
    """Filter out political content from stories.

    Tier 1: Category exclusion (handled by source selection -- no-op here).
    Tier 2: Keyword blocklist with word-boundary matching.
    Tier 3: LLM classification via Claude Haiku (optional).
    """
    if not stories:
        return []

    keywords = _load_keywords(keywords_file)

    # --- Tier 2: Keyword filter ---
    tier2_pass: list[Story] = []
    for story in stories:
        searchable = f"{story.title} {story.summary}"
        if keywords and _keyword_match(searchable, keywords):
            logger.debug("Keyword-filtered: %s", story.title)
            continue
        tier2_pass.append(story)

    logger.info(
        "Keyword filter: %d -> %d stories", len(stories), len(tier2_pass)
    )

    if not use_llm or not tier2_pass:
        return tier2_pass

    # --- Tier 3: LLM classification (batched) ---
    tier3_pass: list[Story] = []
    for batch_start in range(0, len(tier2_pass), _BATCH_SIZE):
        batch = tier2_pass[batch_start : batch_start + _BATCH_SIZE]
        is_political = _llm_classify_batch(batch)
        for story, political in zip(batch, is_political):
            if political:
                logger.debug("LLM-filtered: %s", story.title)
            else:
                tier3_pass.append(story)

    logger.info(
        "LLM filter: %d -> %d stories", len(tier2_pass), len(tier3_pass)
    )

    return tier3_pass
