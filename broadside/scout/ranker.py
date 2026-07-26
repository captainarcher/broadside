"""Satire potential scorer for story ranking."""

from __future__ import annotations

import logging

from broadside.llm import chat
from broadside.scout.sources import Story

logger = logging.getLogger(__name__)

# Weights for composite score
WEIGHT_ABSURDITY = 0.30
WEIGHT_POPULARITY = 0.25
WEIGHT_IRONY = 0.20
WEIGHT_TOPICALITY = 0.15
WEIGHT_TALKABILITY = 0.10

_LLM_BATCH_SIZE = 20


def _normalize_popularity(stories: list[Story]) -> dict[str, float]:
    """Normalize popularity scores to 0-1 range across the story set."""
    if not stories:
        return {}
    scores = [s.popularity_score for s in stories]
    max_score = max(scores) if scores else 1.0
    min_score = min(scores) if scores else 0.0
    span = max_score - min_score
    if span == 0:
        return {s.url: 0.5 for s in stories}
    return {
        s.url: (s.popularity_score - min_score) / span for s in stories
    }


def _llm_score_batch(
    stories: list[Story],
) -> list[dict[str, float]]:
    """Use Claude Haiku to score headlines for absurdity and irony (1-10 each).

    Returns list of dicts with keys: absurdity, irony, topicality, talkability.
    """
    headlines_text = "\n".join(
        f"{i + 1}. {s.title}" for i, s in enumerate(stories)
    )

    prompt = (
        "You are a comedy writer evaluating news headlines for satirical potential. "
        "For each headline, rate the following on a scale of 1-10:\n"
        "- ABSURDITY: How inherently absurd or surprising is this story?\n"
        "- IRONY: How ironic or self-contradictory is the situation?\n"
        "- TOPICALITY: How relevant is this to current cultural conversation?\n"
        "- TALKABILITY: How likely are people to discuss/share this?\n\n"
        f"Headlines:\n{headlines_text}\n\n"
        "Respond with ONLY a numbered list, each line formatted exactly as:\n"
        "N. A=X I=Y T=Z K=W\n"
        "Where X,Y,Z,W are integers 1-10."
    )

    try:
        text = chat(
            model="anthropic/claude-haiku-4.5",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=2048,
        )
        results: list[dict[str, float]] = []

        for line in text.strip().splitlines():
            line = line.strip()
            if not line or not line[0].isdigit():
                continue
            scores: dict[str, float] = {
                "absurdity": 5.0,
                "irony": 5.0,
                "topicality": 5.0,
                "talkability": 5.0,
            }
            for token in line.split():
                if token.startswith("A="):
                    scores["absurdity"] = _parse_score(token[2:])
                elif token.startswith("I="):
                    scores["irony"] = _parse_score(token[2:])
                elif token.startswith("T="):
                    scores["topicality"] = _parse_score(token[2:])
                elif token.startswith("K="):
                    scores["talkability"] = _parse_score(token[2:])
            results.append(scores)

        # Pad to match input length
        default = {"absurdity": 5.0, "irony": 5.0, "topicality": 5.0, "talkability": 5.0}
        while len(results) < len(stories):
            results.append(default)
        return results[: len(stories)]
    except Exception:
        logger.exception("LLM scoring failed")
        return [
            {"absurdity": 5.0, "irony": 5.0, "topicality": 5.0, "talkability": 5.0}
            for _ in stories
        ]


def _parse_score(val: str) -> float:
    """Parse an integer score from LLM output, clamping to 1-10."""
    try:
        n = int(val)
        return float(max(1, min(10, n)))
    except ValueError:
        return 5.0


def _compute_composite(
    llm_scores: dict[str, float],
    popularity_norm: float,
) -> float:
    """Compute weighted composite satire score (0-10 scale)."""
    absurdity = llm_scores.get("absurdity", 5.0)
    irony = llm_scores.get("irony", 5.0)
    topicality = llm_scores.get("topicality", 5.0)
    talkability = llm_scores.get("talkability", 5.0)

    # Popularity is 0-1, scale to 0-10 for uniform weighting
    popularity_scaled = popularity_norm * 10.0

    return (
        WEIGHT_ABSURDITY * absurdity
        + WEIGHT_POPULARITY * popularity_scaled
        + WEIGHT_IRONY * irony
        + WEIGHT_TOPICALITY * topicality
        + WEIGHT_TALKABILITY * talkability
    )


def rank_stories(stories: list[Story]) -> list[Story]:
    """Score and sort stories by satire potential (highest first).

    Composite scoring:
      - Absurdity (30%) -- from LLM
      - Popularity (25%) -- normalized from source signals
      - Irony (20%) -- from LLM
      - Topicality (15%) -- from LLM
      - Talkability (10%) -- from LLM
    """
    if not stories:
        return []

    popularity_map = _normalize_popularity(stories)

    # LLM scoring in batches
    all_llm_scores: list[dict[str, float]] = []
    for batch_start in range(0, len(stories), _LLM_BATCH_SIZE):
        batch = stories[batch_start : batch_start + _LLM_BATCH_SIZE]
        all_llm_scores.extend(_llm_score_batch(batch))

    # Compute composite and attach to raw_metadata
    scored: list[tuple[float, Story]] = []
    for story, llm_scores in zip(stories, all_llm_scores):
        pop_norm = popularity_map.get(story.url, 0.0)
        composite = _compute_composite(llm_scores, pop_norm)

        story.raw_metadata["satire_scores"] = {
            **llm_scores,
            "popularity_norm": pop_norm,
            "composite": round(composite, 3),
        }
        scored.append((composite, story))

    # Sort descending by composite score
    scored.sort(key=lambda x: x[0], reverse=True)

    return [story for _, story in scored]
