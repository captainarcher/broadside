"""HeyGen v3 rendering subsystem for Broadside.

Public API
----------
- :func:`plan_render` -- preview what will be rendered and estimated cost.
- :func:`execute_render` -- run the full render pipeline.
- :func:`retry_scene` -- force re-render a single scene.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from broadside.budget import BudgetGuard
from broadside.config import BroadsideConfig, ShowConfig
from broadside.schema import Episode, RenderManifest, SceneManifestEntry, TalkScene
from broadside.state import RunState

from .hasher import content_hash, scene_exists, scene_filename
from .heygen import SceneResult, render_all_scenes, render_scene, verify_access

__all__ = [
    "RenderPlan",
    "RenderResult",
    "SceneResult",
    "plan_render",
    "execute_render",
    "retry_scene",
]


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class RenderPlan:
    """Preview of an upcoming render batch."""

    scenes_to_render: list[TalkScene] = field(default_factory=list)
    scenes_cached: list[str] = field(default_factory=list)
    estimated_duration: float = 0.0
    estimated_cost: float = 0.0


@dataclass
class RenderResult:
    """Outcome of a completed render batch."""

    scenes_rendered: int = 0
    scenes_cached: int = 0
    total_cost: float = 0.0
    manifest_path: str = ""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_api_key() -> str:
    key = os.environ.get("HEYGEN_API_KEY", "")
    if not key:
        raise RuntimeError(
            "HEYGEN_API_KEY environment variable is not set. "
            "Export it before running renders."
        )
    return key


def _build_dir(config: BroadsideConfig) -> Path:
    return Path("build")


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------

def plan_render(config: BroadsideConfig, episode: Episode) -> RenderPlan:
    """Determine which scenes need rendering and estimate cost.

    Compares content hashes of each :class:`TalkScene` against files
    already on disk under ``build/<episode>/scenes/``.
    """
    show_config = config.get_show(episode.show)
    build = _build_dir(config)
    plan = RenderPlan()

    for scene in episode.talk_scenes:
        chash = content_hash(scene.text, show_config.avatar_id, show_config.voice_id)
        if scene_exists(episode.episode, scene.id, chash, build):
            plan.scenes_cached.append(scene.id)
        else:
            plan.scenes_to_render.append(scene)
            # Rough estimate: ~2.4 words/sec speaking pace
            words = len(scene.text.split())
            est_secs = words / 2.4
            plan.estimated_duration += est_secs
            plan.estimated_cost += est_secs * show_config.cost_per_sec

    return plan


async def execute_render(
    config: BroadsideConfig,
    episode: Episode,
    plan: RenderPlan,
    guard: BudgetGuard,
) -> RenderResult:
    """Run the full render pipeline.

    1. Verify HeyGen access (avatar + voice exist).
    2. Render all pending scenes concurrently.
    3. Write ``render-manifest.json``.
    4. Return :class:`RenderResult`.
    """
    api_key = _get_api_key()
    show_config = config.get_show(episode.show)
    build = _build_dir(config)
    state = RunState.load(episode.episode, build)

    # Initialise scene entries in state
    for scene in episode.talk_scenes:
        state.get_scene(scene.id)
    state.save(build)

    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
        # 1. Verify access
        access_ok = await verify_access(client, api_key, show_config)
        if not access_ok:
            raise RuntimeError(
                "HeyGen access verification failed -- check avatar_id and voice_id "
                "in your show config."
            )

        # 2. Render pending scenes
        results = await render_all_scenes(
            client,
            api_key,
            plan.scenes_to_render,
            show_config,
            build,
            episode.episode,
            state,
            guard,
        )

    # 3. Build and write manifest
    manifest = RenderManifest(episode=episode.episode, show=episode.show)

    # Include both freshly rendered and previously cached scenes
    all_talk = episode.talk_scenes
    for scene in all_talk:
        chash = content_hash(scene.text, show_config.avatar_id, show_config.voice_id)
        fname = scene_filename(scene.id, chash)
        scene_state = state.get_scene(scene.id)

        manifest.scenes.append(
            SceneManifestEntry(
                scene_id=scene.id,
                file=str(build / episode.episode / "scenes" / fname),
                content_hash=chash,
                duration=scene_state.duration,
                cost_usd=scene_state.cost_usd,
                engine="heygen",
            )
        )

    manifest.total_cost_usd = sum(r.cost_usd for r in results)
    manifest.total_duration = sum(
        e.duration for e in manifest.scenes
    )

    manifest_path = build / episode.episode / "render-manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with open(manifest_path, "w") as f:
        json.dump(manifest.model_dump(), f, indent=2)

    rendered_count = sum(1 for r in results if not r.cached)
    cached_count = sum(1 for r in results if r.cached) + len(plan.scenes_cached)

    return RenderResult(
        scenes_rendered=rendered_count,
        scenes_cached=cached_count,
        total_cost=manifest.total_cost_usd,
        manifest_path=str(manifest_path),
    )


async def retry_scene(
    config: BroadsideConfig,
    episode_id: str,
    scene_id: str,
) -> str:
    """Force re-render a single scene, ignoring cache.

    Returns the path to the newly rendered MP4 file.
    """
    api_key = _get_api_key()
    build = _build_dir(config)

    # Load episode to find the scene
    episode_path = build / episode_id / f"{episode_id}.yaml"
    episode = Episode.load(episode_path)
    show_config = config.get_show(episode.show)

    target_scene: TalkScene | None = None
    for scene in episode.talk_scenes:
        if scene.id == scene_id:
            target_scene = scene
            break

    if target_scene is None:
        raise ValueError(
            f"Scene '{scene_id}' not found in episode '{episode_id}'. "
            f"Available: {[s.id for s in episode.talk_scenes]}"
        )

    # Delete existing file if present so render_scene does a fresh render
    chash = content_hash(
        target_scene.text, show_config.avatar_id, show_config.voice_id
    )
    existing = build / episode_id / "scenes" / scene_filename(scene_id, chash)
    if existing.exists():
        existing.unlink()

    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
        result = await render_scene(
            client, api_key, target_scene, show_config, build, episode_id
        )

    # Update state
    state = RunState.load(episode_id, build)
    state.set_scene_status(
        scene_id,
        "complete",
        content_hash=result.content_hash,
        file=result.file,
        cost_usd=result.cost_usd,
        duration=result.duration,
    )
    state.save(build)

    return result.file
