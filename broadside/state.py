"""Run state tracking for idempotent, resumable pipeline execution.

State file per episode at build/<episode>/state.json tracks per-scene
render status so crashed or re-fired runs pick up where they left off.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


SceneStatus = Literal["pending", "rendering", "complete", "failed"]


class SceneState(BaseModel):
    scene_id: str
    status: SceneStatus = "pending"
    content_hash: str = ""
    file: str = ""
    error: str = ""
    cost_usd: float = 0.0
    duration: float = 0.0


class RunState(BaseModel):
    episode: str
    scenes: dict[str, SceneState] = Field(default_factory=dict)
    assembly_status: Literal["pending", "in_progress", "complete", "failed"] = "pending"
    assembly_engine: str = ""

    @classmethod
    def load(cls, episode_id: str, build_dir: Path = Path("build")) -> RunState:
        path = build_dir / episode_id / "state.json"
        if not path.exists():
            return cls(episode=episode_id)
        with open(path) as f:
            data = json.load(f)
        return cls.model_validate(data)

    def save(self, build_dir: Path = Path("build")) -> None:
        path = build_dir / self.episode / "state.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(self.model_dump(), f, indent=2)

    def get_scene(self, scene_id: str) -> SceneState:
        if scene_id not in self.scenes:
            self.scenes[scene_id] = SceneState(scene_id=scene_id)
        return self.scenes[scene_id]

    def set_scene_status(
        self,
        scene_id: str,
        status: SceneStatus,
        *,
        content_hash: str = "",
        file: str = "",
        error: str = "",
        cost_usd: float = 0.0,
        duration: float = 0.0,
    ) -> None:
        scene = self.get_scene(scene_id)
        scene.status = status
        if content_hash:
            scene.content_hash = content_hash
        if file:
            scene.file = file
        if error:
            scene.error = error
        if cost_usd:
            scene.cost_usd = cost_usd
        if duration:
            scene.duration = duration

    @property
    def pending_scenes(self) -> list[str]:
        return [
            sid
            for sid, s in self.scenes.items()
            if s.status in ("pending", "failed")
        ]

    @property
    def complete_scenes(self) -> list[str]:
        return [sid for sid, s in self.scenes.items() if s.status == "complete"]

    @property
    def all_scenes_complete(self) -> bool:
        return all(s.status == "complete" for s in self.scenes.values())
