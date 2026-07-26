"""Content hashing for idempotent scene rendering.

Generates deterministic hashes from scene content so unchanged scenes
can be skipped on re-runs.  Hash covers script text + avatar + voice
so any change to those inputs triggers a fresh render.
"""

from __future__ import annotations

import hashlib
from pathlib import Path


def content_hash(text: str, avatar_id: str, voice_id: str) -> str:
    """SHA-256 of concatenated inputs, truncated to 12 hex chars."""
    payload = f"{text}|{avatar_id}|{voice_id}"
    return hashlib.sha256(payload.encode()).hexdigest()[:12]


def scene_filename(scene_id: str, hash_value: str) -> str:
    """Deterministic filename: ``{scene_id}-{hash}.mp4``."""
    return f"{scene_id}-{hash_value}.mp4"


def scene_exists(
    episode_id: str, scene_id: str, hash_value: str, build_dir: Path
) -> bool:
    """Return *True* if the rendered file already exists on disk."""
    fname = scene_filename(scene_id, hash_value)
    path = build_dir / episode_id / "scenes" / fname
    return path.is_file()
