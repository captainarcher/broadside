"""Multi-platform publishing subsystem for Broadside.

All publishing is human-initiated -- never auto-post.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from ..config import BroadsideConfig
from ..schema import Episode, PublishManifest, PublishEntry

Platform = Literal["youtube", "twitter", "instagram", "tiktok"]

_PLATFORMS: dict[str, object] = {}  # lazy-loaded


def _get_publisher(platform: str):
    """Lazy-import the platform publisher to avoid heavy imports at startup."""
    if platform == "youtube":
        from .youtube import publish_to_youtube
        return publish_to_youtube
    elif platform in ("twitter", "x"):
        from .twitter import publish_to_twitter
        return publish_to_twitter
    elif platform == "instagram":
        from .instagram import publish_to_instagram
        return publish_to_instagram
    elif platform == "tiktok":
        from .tiktok import publish_to_tiktok
        return publish_to_tiktok
    else:
        raise ValueError(
            f"Unknown platform '{platform}'. "
            f"Supported: youtube, twitter, instagram, tiktok"
        )


def _build_metadata(episode: Episode, platform: str) -> dict:
    """Build platform-specific metadata from episode data.

    Maps episode fields to the metadata dict expected by each publisher:
    - caption_hook -> title (YouTube) / caption (social platforms)
    - source_story -> description context
    - show -> hashtag base
    """
    caption = episode.caption_hook or episode.episode
    source = episode.source_story

    # Build description from source story
    description_parts = [caption]
    if source.headline:
        description_parts.append(f"\nStory: {source.headline}")
    if source.source:
        description_parts.append(f"Source: {source.source}")
    if source.url:
        description_parts.append(f"Link: {source.url}")
    description = "\n".join(description_parts)

    # Default hashtags based on show
    hashtags = [episode.show.replace("-", "")]
    if episode.show == "bs":
        hashtags.extend(["broadside", "comedy", "news", "satire"])
    elif episode.show == "audit-trail":
        hashtags.extend(["audittrail", "comedy", "news"])

    # Tags for YouTube (longer list)
    tags = hashtags + ["shorts", "comedy", "news", "viral"]

    return {
        "title": caption,
        "caption": caption,
        "description": description,
        "tags": tags,
        "hashtags": hashtags,
    }


def _load_episode(episode_id: str, out_dir: Path = Path("out")) -> Episode:
    """Load episode YAML from output dir or standard episode directories."""
    # Search in output dir, then drafts, approved, rendered
    search_dirs = [
        out_dir / episode_id,
        Path("episodes/drafts"),
        Path("episodes/approved"),
        Path("episodes/rendered"),
    ]

    for search_dir in search_dirs:
        if not search_dir.exists():
            continue
        for candidate in [
            search_dir / f"{episode_id}.yaml",
            search_dir / f"{episode_id}.yml",
            search_dir / "episode.yaml",
        ]:
            if candidate.exists():
                return Episode.load(candidate)
        # Also glob for any YAML containing the episode ID
        for pattern in ["*.yaml", "*.yml"]:
            for f in search_dir.glob(pattern):
                if episode_id in f.stem:
                    return Episode.load(f)

    raise FileNotFoundError(
        f"No episode YAML found for '{episode_id}'. "
        f"Searched: {', '.join(str(d) for d in search_dirs)}"
    )


def _find_video(episode_id: str, out_dir: Path = Path("out")) -> Path:
    """Locate the final rendered video for an episode."""
    episode_dir = out_dir / episode_id

    # Primary: final-<episode_id>.mp4
    primary = episode_dir / f"final-{episode_id}.mp4"
    if primary.exists():
        return primary

    # Fallback: any .mp4 in the directory
    mp4_files = list(episode_dir.glob("*.mp4"))
    if mp4_files:
        # Prefer files with "final" in the name
        for f in mp4_files:
            if "final" in f.stem.lower():
                return f
        return mp4_files[0]

    raise FileNotFoundError(
        f"No video found in {episode_dir}. "
        f"Expected final-{episode_id}.mp4"
    )


def _load_publish_manifest(
    episode_id: str, out_dir: Path = Path("out")
) -> PublishManifest:
    """Load or create a publish manifest for the episode."""
    manifest_path = out_dir / episode_id / "publish-manifest.json"
    if manifest_path.exists():
        with open(manifest_path) as f:
            data = json.load(f)
        return PublishManifest.model_validate(data)
    return PublishManifest(episode=episode_id)


def _save_publish_manifest(
    manifest: PublishManifest, out_dir: Path = Path("out")
) -> Path:
    """Save publish manifest to disk."""
    manifest_path = out_dir / manifest.episode / "publish-manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with open(manifest_path, "w") as f:
        json.dump(manifest.model_dump(), f, indent=2)
    return manifest_path


def publish_episode(
    config: BroadsideConfig,
    episode_id: str,
    platform: str,
    out_dir: Path = Path("out"),
) -> str:
    """Publish an episode to a specific platform.

    This is the main entry point for all publishing. It:
    1. Loads episode metadata from out/<episode_id>/
    2. Finds the final video at out/<episode_id>/final-<episode_id>.mp4
    3. Builds platform-specific metadata from the episode YAML
    4. Routes to the correct platform publisher
    5. Saves the result to publish-manifest.json
    6. Returns the published URL

    Parameters
    ----------
    config : BroadsideConfig
        Project configuration.
    episode_id : str
        Episode identifier (e.g., "bs-2024-01-15-01").
    platform : str
        Target platform: youtube, twitter, instagram, tiktok.
    out_dir : Path
        Output directory containing episode artifacts.

    Returns
    -------
    str
        URL of the published content.
    """
    print(f"\n--- Publishing {episode_id} to {platform} ---\n")

    # Load episode data and find video
    episode = _load_episode(episode_id, out_dir)
    video_path = _find_video(episode_id, out_dir)
    metadata = _build_metadata(episode, platform)

    print(f"Episode: {episode.episode}")
    print(f"Video: {video_path}")
    print(f"Caption: {metadata['caption'][:80]}...")
    print()

    # Get the platform publisher and execute
    publisher = _get_publisher(platform)
    url = publisher(config, episode_id, video_path, metadata)

    # Update publish manifest
    manifest = _load_publish_manifest(episode_id, out_dir)

    # Check if platform already has an entry and update it
    existing = next(
        (e for e in manifest.entries if e.platform == platform), None
    )
    if existing:
        existing.url = url
        existing.status = "published"
        existing.published_at = datetime.now(timezone.utc).isoformat()
    else:
        manifest.entries.append(
            PublishEntry(
                platform=platform,
                url=url,
                status="published",
                published_at=datetime.now(timezone.utc).isoformat(),
            )
        )

    manifest_path = _save_publish_manifest(manifest, out_dir)
    print(f"\nManifest updated: {manifest_path}")

    return url
