"""HeyGen v3 API client for avatar video rendering.

Handles access verification, single-scene rendering with idempotency,
and batch rendering with concurrency control and budget tracking.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from broadside.budget import BudgetGuard
from broadside.config import ShowConfig
from broadside.schema import TalkScene
from broadside.state import RunState

from .hasher import content_hash, scene_exists, scene_filename
from .poller import HEYGEN_BASE, poll_video_status

log = logging.getLogger(__name__)

import asyncio


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class SceneResult:
    """Outcome of rendering a single talk scene."""

    scene_id: str
    file: str
    content_hash: str
    duration: float = 0.0
    cost_usd: float = 0.0
    cached: bool = False
    error: str = ""


# ---------------------------------------------------------------------------
# Access verification
# ---------------------------------------------------------------------------

async def verify_access(
    client: httpx.AsyncClient,
    api_key: str,
    show_config: ShowConfig,
) -> bool:
    """Confirm that the configured avatar and voice exist in the account.

    Hits ``GET /v3/avatars/looks`` and ``GET /v3/voices`` and checks
    whether *show_config.avatar_id* and *show_config.voice_id* appear.
    Prints available options when a configured ID is not found.

    Returns *True* only when **both** IDs are confirmed.
    """
    headers = {"X-Api-Key": api_key}
    ok = True

    # -- avatars --
    resp = await client.get(f"{HEYGEN_BASE}/v3/avatars/looks", headers=headers)
    resp.raise_for_status()
    avatar_data = resp.json().get("data", [])
    # Flatten -- API may return list of dicts or nested structure
    avatar_ids: set[str] = set()
    if isinstance(avatar_data, list):
        for item in avatar_data:
            if isinstance(item, dict):
                aid = item.get("avatar_id") or item.get("id", "")
                if aid:
                    avatar_ids.add(aid)
                # Also check nested looks
                for look in item.get("looks", []):
                    lid = look.get("look_id") or look.get("id", "")
                    if lid:
                        avatar_ids.add(lid)

    if show_config.avatar_id not in avatar_ids:
        log.error(
            "Avatar '%s' not found. Available: %s",
            show_config.avatar_id,
            ", ".join(sorted(avatar_ids)) or "(none)",
        )
        ok = False
    else:
        log.info("Avatar '%s' verified.", show_config.avatar_id)

    # -- voices (check both public and private) --
    voice_ids: set[str] = set()
    for vtype in ("public", "private"):
        resp = await client.get(
            f"{HEYGEN_BASE}/v3/voices",
            headers=headers,
            params={"type": vtype, "limit": 100},
        )
        resp.raise_for_status()
        voice_data = resp.json().get("data", [])
        if isinstance(voice_data, list):
            for item in voice_data:
                if isinstance(item, dict):
                    vid = item.get("voice_id") or item.get("id", "")
                    if vid:
                        voice_ids.add(vid)

    if show_config.voice_id not in voice_ids:
        log.error(
            "Voice '%s' not found. Available: %s",
            show_config.voice_id,
            ", ".join(sorted(voice_ids)) or "(none)",
        )
        ok = False
    else:
        log.info("Voice '%s' verified.", show_config.voice_id)

    return ok


# ---------------------------------------------------------------------------
# Single scene render
# ---------------------------------------------------------------------------

async def render_scene(
    client: httpx.AsyncClient,
    api_key: str,
    scene: TalkScene,
    show_config: ShowConfig,
    build_dir: Path,
    episode_id: str,
) -> SceneResult:
    """Render one *TalkScene* via the HeyGen v3 video creation API.

    1. Compute content hash; skip if the output file already exists.
    2. ``POST /v3/videos`` with avatar payload and ``Idempotency-Key``.
    3. Poll until complete.
    4. Download the MP4 to ``build/<episode>/scenes/<id>-<hash>.mp4``.
    5. Return a :class:`SceneResult`.
    """
    chash = content_hash(scene.text, show_config.avatar_id, show_config.voice_id)
    fname = scene_filename(scene.id, chash)
    scenes_dir = build_dir / episode_id / "scenes"

    # Fast-path: already rendered with same content
    if scene_exists(episode_id, scene.id, chash, build_dir):
        log.info("Scene %s cached (hash %s)", scene.id, chash)
        return SceneResult(
            scene_id=scene.id,
            file=str(scenes_dir / fname),
            content_hash=chash,
            cached=True,
        )

    scenes_dir.mkdir(parents=True, exist_ok=True)
    headers = {
        "X-Api-Key": api_key,
        "Content-Type": "application/json",
        "Idempotency-Key": str(uuid.uuid4()),
    }

    payload = {
        "type": "avatar",
        "avatar_id": show_config.avatar_id,
        "voice_id": show_config.voice_id,
        "script": scene.text,
        "aspect_ratio": show_config.aspect_ratio,
        "background": {"type": "color", "value": show_config.background_color},
        "engine": {"type": show_config.engine},
    }

    resp = await client.post(
        f"{HEYGEN_BASE}/v3/videos", headers=headers, json=payload
    )
    resp.raise_for_status()
    video_id = resp.json()["data"]["video_id"]
    log.info("Scene %s submitted as video %s", scene.id, video_id)

    # Poll until done
    video_data = await poll_video_status(client, video_id, api_key)

    # Download MP4
    download_url = video_data.get("video_url") or video_data.get("download_url") or video_data.get("url", "")
    if not download_url:
        raise RuntimeError(
            f"No download URL in completed video data for {video_id}"
        )

    dl_resp = await client.get(download_url)
    dl_resp.raise_for_status()
    out_path = scenes_dir / fname
    out_path.write_bytes(dl_resp.content)

    duration = float(video_data.get("duration", 0))
    cost = duration * show_config.cost_per_sec

    log.info(
        "Scene %s rendered: %.1fs, $%.3f -> %s",
        scene.id,
        duration,
        cost,
        out_path,
    )

    return SceneResult(
        scene_id=scene.id,
        file=str(out_path),
        content_hash=chash,
        duration=duration,
        cost_usd=cost,
    )


# ---------------------------------------------------------------------------
# Batch render
# ---------------------------------------------------------------------------

async def render_all_scenes(
    client: httpx.AsyncClient,
    api_key: str,
    scenes: list[TalkScene],
    show_config: ShowConfig,
    build_dir: Path,
    episode_id: str,
    state: RunState,
    guard: BudgetGuard,
) -> list[SceneResult]:
    """Render all *scenes* with concurrency capped at 10.

    * Skips scenes already marked ``complete`` in *state*.
    * Updates *state* after each scene (persisted to disk).
    * Records spend through *guard*.
    """
    sem = asyncio.Semaphore(10)
    results: list[SceneResult] = []
    lock = asyncio.Lock()

    async def _render_one(scene: TalkScene) -> None:
        # Skip if state says complete and file still exists
        scene_state = state.get_scene(scene.id)
        chash = content_hash(scene.text, show_config.avatar_id, show_config.voice_id)

        if (
            scene_state.status == "complete"
            and scene_state.content_hash == chash
            and scene_exists(episode_id, scene.id, chash, build_dir)
        ):
            fname = scene_filename(scene.id, chash)
            result = SceneResult(
                scene_id=scene.id,
                file=str(build_dir / episode_id / "scenes" / fname),
                content_hash=chash,
                duration=scene_state.duration,
                cost_usd=0.0,
                cached=True,
            )
            async with lock:
                results.append(result)
            return

        state.set_scene_status(scene.id, "rendering", content_hash=chash)
        state.save(build_dir)

        async with sem:
            try:
                result = await render_scene(
                    client, api_key, scene, show_config, build_dir, episode_id
                )
            except Exception as exc:
                state.set_scene_status(
                    scene.id, "failed", content_hash=chash, error=str(exc)
                )
                state.save(build_dir)
                raise

        state.set_scene_status(
            scene.id,
            "complete",
            content_hash=result.content_hash,
            file=result.file,
            cost_usd=result.cost_usd,
            duration=result.duration,
        )
        state.save(build_dir)

        if result.cost_usd > 0 and not result.cached:
            guard.record_spend(
                "heygen",
                f"scene {scene.id} ({episode_id})",
                result.cost_usd,
            )

        async with lock:
            results.append(result)

    tasks = [asyncio.create_task(_render_one(s)) for s in scenes]
    await asyncio.gather(*tasks)

    return results
