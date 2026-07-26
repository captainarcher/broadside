"""Manifest I/O utilities for render and publish manifests."""

from __future__ import annotations

import json
from pathlib import Path

from .schema import RenderManifest, PublishManifest, SceneManifestEntry, PublishEntry


def load_render_manifest(episode_id: str, build_dir: Path = Path("build")) -> RenderManifest | None:
    path = build_dir / episode_id / "render-manifest.json"
    if not path.exists():
        return None
    with open(path) as f:
        data = json.load(f)
    return RenderManifest.model_validate(data)


def save_render_manifest(manifest: RenderManifest, build_dir: Path = Path("build")) -> Path:
    path = build_dir / manifest.episode / "render-manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(manifest.model_dump(), f, indent=2)
    return path


def load_publish_manifest(episode_id: str, out_dir: Path = Path("out")) -> PublishManifest | None:
    path = out_dir / episode_id / "publish-manifest.json"
    if not path.exists():
        return None
    with open(path) as f:
        data = json.load(f)
    return PublishManifest.model_validate(data)


def save_publish_manifest(manifest: PublishManifest, out_dir: Path = Path("out")) -> Path:
    path = out_dir / manifest.episode / "publish-manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(manifest.model_dump(), f, indent=2)
    return path
