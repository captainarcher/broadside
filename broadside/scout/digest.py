"""Output formatting and persistence for the scout pipeline."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from broadside.scout.sources import Story

logger = logging.getLogger(__name__)

DEFAULT_OUTPUT_PATH = "scout-digest.json"
DEFAULT_TOP_N = 20


def save_digest(
    stories: list[Story],
    output_path: str = DEFAULT_OUTPUT_PATH,
    top_n: int = DEFAULT_TOP_N,
) -> Path:
    """Save top stories to a JSON file.

    Returns the path to the written file.
    """
    top_stories = stories[:top_n]
    payload = {
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "count": len(top_stories),
        "stories": [asdict(s) for s in top_stories],
    }

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str))
    logger.info("Saved %d stories to %s", len(top_stories), path)
    return path


def format_digest(
    stories: list[Story],
    top_n: int = DEFAULT_TOP_N,
) -> str:
    """Format a human-readable digest string for notification."""
    top_stories = stories[:top_n]
    now = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines = [
        f"BROADSIDE SCOUT DIGEST -- {now}",
        f"Top {len(top_stories)} stories ranked by satire potential",
        "=" * 60,
        "",
    ]

    for i, story in enumerate(top_stories, 1):
        score = story.raw_metadata.get("satire_scores", {}).get("composite", 0)
        lines.append(f"{i:>2}. [{score:.1f}] {story.title}")
        lines.append(f"    Source: {story.source}  |  Category: {story.category}")
        if story.summary:
            # Truncate long summaries
            summary = story.summary[:120] + ("..." if len(story.summary) > 120 else "")
            lines.append(f"    {summary}")
        lines.append(f"    {story.url}")
        lines.append("")

    lines.append("=" * 60)
    lines.append(f"Total stories evaluated: pipeline output of {len(top_stories)}")

    return "\n".join(lines)
