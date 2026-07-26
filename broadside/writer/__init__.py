"""Comedy writing pipeline -- from news story to polished episode draft.

Four-pass pipeline:
  1. Angle mining   -- find satirical angles in the story
  2. Joke generation -- generate 8 candidate reactions per angle
  3. Script assembly -- arrange into Broadside episode skeleton with alternates
  4. Voice polish    -- rewrite in Benn Stone's voice (Opus)
"""

from __future__ import annotations

import json
import re
from datetime import date, timedelta
from pathlib import Path

import click
import yaml

from broadside.config import BroadsideConfig
from broadside.schema import Episode, SourceStory
from broadside.writer.angles import mine_angles
from broadside.writer.assembly import assemble_script
from broadside.writer.character import (
    format_character_context,
    load_character_sheet,
    load_example_bank,
    load_voice_spec,
)
from broadside.writer.jokes import generate_jokes
from broadside.writer.polish import polish_script, save_draft

# --- Banned topics from BENN_VOICE.md section 2 ---
_BANNED_TOPICS = [
    "politics", "government", "elections", "tragedy",
    "layoffs-as-suffering", "security scares",
]

# --- Lore quotas (per calendar week) ---
_KEVIN_WEEKLY_QUOTA = 1
_FAN_WEEKLY_QUOTA = 1


def _count_lore_usage_this_week(
    drafts_dir: Path,
    lore_term: str,
) -> int:
    """Count how many times a lore element appears in this week's drafts."""
    today = date.today()
    week_start = today - timedelta(days=today.weekday())  # Monday
    count = 0
    if not drafts_dir.is_dir():
        return 0
    for f in drafts_dir.glob("*.yaml"):
        # Check file modification date
        import os
        mtime = date.fromtimestamp(os.path.getmtime(f))
        if mtime >= week_start:
            content = f.read_text().lower()
            if lore_term.lower() in content:
                count += 1
    return count


def _check_banned_topics(text: str) -> list[str]:
    """Return list of banned topic violations found in text."""
    violations = []
    text_lower = text.lower()
    for topic in _BANNED_TOPICS:
        if topic.lower() in text_lower:
            violations.append(topic)
    return violations


def _enforce_quotas(
    episode_text: str,
    drafts_dir: Path = Path("episodes/drafts"),
) -> list[str]:
    """Check lore quotas and return warnings if exceeded.

    Returns list of warning strings (empty if all quotas OK).
    """
    warnings: list[str] = []

    # Kevin quota
    if "kevin" in episode_text.lower():
        kevin_count = _count_lore_usage_this_week(drafts_dir, "kevin")
        if kevin_count >= _KEVIN_WEEKLY_QUOTA:
            warnings.append(
                f"QUOTA EXCEEDED: Kevin already used {kevin_count} time(s) this week "
                f"(max {_KEVIN_WEEKLY_QUOTA}/week). Remove Kevin reference."
            )

    # Fan quota (check for orbit references)
    fan_patterns = ["the fan", "mechanical reason", "nothing fell from the ceiling", "sealed"]
    fan_used = any(p in episode_text.lower() for p in fan_patterns)
    if fan_used:
        fan_count = _count_lore_usage_this_week(drafts_dir, "mechanical reason")
        fan_count += _count_lore_usage_this_week(drafts_dir, "the fan")
        if fan_count >= _FAN_WEEKLY_QUOTA:
            warnings.append(
                f"QUOTA EXCEEDED: Fan orbit already used {fan_count} time(s) this week "
                f"(max {_FAN_WEEKLY_QUOTA}/week). Remove fan reference."
            )

    return warnings


def _load_story_from_ref(story_ref: str) -> SourceStory:
    """Load a single story from a file path, URL, digest index, or headline.

    Supports:
      - File path (.yaml/.json) -- load directly
      - Inline JSON string -- parse directly
      - URL -- look up in scout-digest.json, or fetch article content
      - Digest index (e.g., "3") -- load Nth story from digest
      - Headline text -- use as-is
    """
    # File path
    path = Path(story_ref)
    if path.exists():
        with open(path) as f:
            data = yaml.safe_load(f) if path.suffix in (".yaml", ".yml") else json.load(f)
        return SourceStory.model_validate(data)

    # Inline JSON
    try:
        data = json.loads(story_ref)
        return SourceStory.model_validate(data)
    except (json.JSONDecodeError, ValueError):
        pass

    # Digest index (e.g., "3" or "#3")
    index_ref = story_ref.lstrip("#").strip()
    if index_ref.isdigit():
        digest_path = Path("scout-digest.json")
        if digest_path.exists():
            with open(digest_path) as f:
                digest = json.load(f)
            stories = digest if isinstance(digest, list) else digest.get("stories", [])
            idx = int(index_ref) - 1  # 1-indexed for user
            if 0 <= idx < len(stories):
                s = stories[idx]
                return SourceStory(
                    headline=s.get("title", ""),
                    source=s.get("source", ""),
                    url=s.get("url", ""),
                )

    # URL -- look up in scout digest first
    if story_ref.startswith("http"):
        digest_path = Path("scout-digest.json")
        if digest_path.exists():
            with open(digest_path) as f:
                digest = json.load(f)
            stories = digest if isinstance(digest, list) else digest.get("stories", [])
            for s in stories:
                if s.get("url", "") == story_ref:
                    return SourceStory(
                        headline=s.get("title", ""),
                        source=s.get("source", ""),
                        url=s.get("url", ""),
                    )

        # Not in digest -- try to extract article content
        try:
            from newspaper import Article

            article = Article(story_ref)
            article.download()
            article.parse()
            return SourceStory(
                headline=article.title or story_ref,
                source=article.source_url or "",
                url=story_ref,
            )
        except Exception:
            # Fall through to headline-only
            pass

    # Treat as a headline string
    return SourceStory(headline=story_ref)


def _load_batch_stories(digest_path: str = "scout-digest.json") -> list[SourceStory]:
    """Load stories from the scout digest file."""
    path = Path(digest_path)
    if not path.exists():
        raise FileNotFoundError(
            f"Scout digest not found at {path}. Run 'broadside scout' first."
        )
    with open(path) as f:
        data = json.load(f)

    stories = data if isinstance(data, list) else data.get("stories", [])
    return [SourceStory.model_validate(s) for s in stories]


def _run_single_story(
    story: SourceStory,
    config: BroadsideConfig,
    *,
    interactive: bool = True,
) -> Episode | None:
    """Run the full 4-pass pipeline on a single story.

    In interactive mode, pauses after each pass for user review.
    Returns the final Episode or None if the user aborts.
    """
    comedy = config.comedy

    # --- Pre-check: banned topics in headline ---
    banned_hits = _check_banned_topics(story.headline)
    if banned_hits:
        click.echo(click.style(
            f"  BLOCKED: Story touches banned topics: {', '.join(banned_hits)}",
            fg="red", bold=True,
        ))
        return None

    # --- Pass 1: Angle mining ---
    click.echo(click.style("\n[Pass 1] Angle Mining", fg="cyan", bold=True))
    click.echo(f"  Story: {story.headline}")
    if story.url:
        click.echo(f"  URL: {story.url}")

    angles = mine_angles(
        headline=story.headline,
        summary=f"Source: {story.source}. URL: {story.url}",
        url=story.url,
        key_quotes=story.key_quotes,
        config=comedy,
    )

    # Display archetype tag if present
    archetype = None
    display_angles = []
    for a in angles:
        if a.upper().startswith("ARCHETYPE:"):
            archetype = a.split(":", 1)[1].strip()
            click.echo(f"  Archetype: {archetype}")
        else:
            display_angles.append(a)

    click.echo(f"\n  Found {len(display_angles)} angles:")
    for i, a in enumerate(display_angles, 1):
        click.echo(f"    {i}. {a}")

    if interactive:
        if not click.confirm("\n  Continue to joke generation?", default=True):
            return None
        # Let user pick angles (default: first 3)
        picks = click.prompt(
            "  Select angles (comma-separated numbers, or Enter for top 3)",
            default=",".join(str(i) for i in range(1, min(4, len(display_angles) + 1))),
        )
        selected_indices = [int(x.strip()) - 1 for x in picks.split(",") if x.strip().isdigit()]
        selected_angles = [display_angles[i] for i in selected_indices if 0 <= i < len(display_angles)]
    else:
        selected_angles = display_angles[:3]

    if not selected_angles:
        click.echo("  No angles selected, skipping story.")
        return None

    # --- Pass 2: Joke generation (8 candidates per angle) ---
    click.echo(click.style("\n[Pass 2] Joke Generation (8 candidates/angle)", fg="cyan", bold=True))

    jokes = generate_jokes(selected_angles, config=comedy)

    total_candidates = 0
    for angle, variants in jokes.items():
        click.echo(f"\n  Angle: {angle}")
        for i, v in enumerate(variants, 1):
            click.echo(f"    {i}. [{v.get('structure', '?')}] {v['joke']}")
            total_candidates += 1
    click.echo(f"\n  Total candidates: {total_candidates}")

    if interactive:
        if not click.confirm("\n  Continue to script assembly?", default=True):
            return None

    # --- Pass 3: Script assembly (with alternates) ---
    click.echo(click.style("\n[Pass 3] Script Assembly", fg="cyan", bold=True))

    episode = assemble_script(jokes, story, config=comedy)

    click.echo(f"\n  Episode: {episode.episode}")
    click.echo(f"  Caption: {episode.caption_hook}")
    click.echo(f"  Scenes: {len(episode.scenes)}")
    click.echo(f"  Word count: {episode.word_count}")
    click.echo(f"  Est. duration: {episode.estimated_duration:.1f}s")
    click.echo("\n  Script (top picks):")
    for scene in episode.scenes:
        if hasattr(scene, "text"):
            click.echo(f"    [{scene.id}] {scene.text}")
            # Show alternates count if available
            if hasattr(scene, "alternates") and scene.alternates:
                click.echo(f"         + {len(scene.alternates)} alternates")

    if interactive:
        if not click.confirm("\n  Continue to voice polish?", default=True):
            # Save unpolished draft
            path = save_draft(episode)
            click.echo(f"  Saved unpolished draft: {path}")
            return episode

    # --- Pass 4: Voice polish ---
    click.echo(click.style("\n[Pass 4] Voice Polish (Opus)", fg="cyan", bold=True))

    polished = polish_script(episode, config=comedy)

    click.echo(f"\n  Word count: {polished.word_count}")
    click.echo(f"  Est. duration: {polished.estimated_duration:.1f}s")
    click.echo("\n  Polished script:")
    for scene in polished.scenes:
        if hasattr(scene, "text"):
            click.echo(f"    [{scene.id}] {scene.text}")

    # --- Post-pipeline checks ---
    # Collect all text for quota/banned checks
    all_text = " ".join(
        scene.text for scene in polished.scenes if hasattr(scene, "text")
    )

    # Check banned topics in output
    banned_hits = _check_banned_topics(all_text)
    if banned_hits:
        click.echo(click.style(
            f"\n  WARNING: Output contains banned topics: {', '.join(banned_hits)}",
            fg="red", bold=True,
        ))
        click.echo("  These must be removed before approval.")

    # Enforce lore quotas
    quota_warnings = _enforce_quotas(all_text)
    for w in quota_warnings:
        click.echo(click.style(f"\n  WARNING: {w}", fg="yellow", bold=True))

    # Save final draft (with ALL candidates preserved)
    path = save_draft(polished)
    click.echo(click.style(f"\n  Saved: {path}", fg="green", bold=True))

    # Also save full candidates file alongside for the kill floor
    candidates_path = path.parent / f"{polished.episode}-candidates.yaml"
    with open(candidates_path, "w") as f:
        yaml.dump(
            {"angles": jokes, "archetype": archetype},
            f,
            default_flow_style=False,
            sort_keys=False,
            allow_unicode=True,
        )
    click.echo(f"  Candidates: {candidates_path}")

    return polished


def run_writing_pipeline(
    config: BroadsideConfig,
    story_ref: str | None = None,
    batch_mode: bool = False,
) -> list[Episode]:
    """Run the comedy writing pipeline.

    Args:
        config: Broadside configuration.
        story_ref: Path/JSON/headline for a single story. Ignored in batch mode.
        batch_mode: If True, load stories from scout-digest.json and process all.

    Returns:
        List of completed Episode objects.
    """
    episodes: list[Episode] = []

    if batch_mode:
        stories = _load_batch_stories()
        click.echo(f"Batch mode: {len(stories)} stories from scout digest.")
        for i, story in enumerate(stories, 1):
            click.echo(click.style(f"\n{'='*60}", fg="yellow"))
            click.echo(click.style(f"Story {i}/{len(stories)}: {story.headline}", fg="yellow"))
            result = _run_single_story(story, config, interactive=True)
            if result:
                episodes.append(result)
    elif story_ref:
        story = _load_story_from_ref(story_ref)
        result = _run_single_story(story, config, interactive=True)
        if result:
            episodes.append(result)
    else:
        click.echo("No story provided. Use --story or --batch flag.")
        raise click.UsageError("Provide a story reference or use batch mode.")

    click.echo(click.style(f"\nPipeline complete. {len(episodes)} episode(s) drafted.", fg="green"))
    return episodes
