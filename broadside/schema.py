"""Pydantic schemas for episode YAML, ad concepts, and manifests."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field


class SourceStory(BaseModel):
    headline: str = ""
    source: str = ""
    url: str = ""
    key_quotes: list[str] = Field(default_factory=list)


class TalkScene(BaseModel):
    id: str
    type: Literal["talk"] = "talk"
    text: str
    pause_after: float = 0.0
    zoom: bool = False


class CardScene(BaseModel):
    id: str
    type: Literal["card"] = "card"
    asset: str
    duration: float = 2.0
    audio: Literal["none", "continue"] = "none"


class SilentScene(BaseModel):
    id: str
    type: Literal["silent"] = "silent"
    duration: float = 1.0
    overlay: str | None = None


class AdScene(BaseModel):
    id: str
    type: Literal["ad"] = "ad"
    concept: str
    duration: float = 12.0


Scene = TalkScene | CardScene | SilentScene | AdScene


class EndCard(BaseModel):
    wordmark: str
    text: str
    duration: float = 2.0


class Episode(BaseModel):
    episode: str
    show: str
    post_day: str = ""
    caption_hook: str = ""
    source_story: SourceStory = SourceStory()
    scenes: list[Scene] = Field(default_factory=list)
    end_card: EndCard | None = None

    @classmethod
    def load(cls, path: str | Path) -> Episode:
        path = Path(path)
        with open(path) as f:
            data = yaml.safe_load(f)
        return cls.model_validate(data)

    @property
    def talk_scenes(self) -> list[TalkScene]:
        return [s for s in self.scenes if isinstance(s, TalkScene)]

    @property
    def card_scenes(self) -> list[CardScene]:
        return [s for s in self.scenes if isinstance(s, CardScene)]

    @property
    def word_count(self) -> int:
        return sum(len(s.text.split()) for s in self.talk_scenes)

    @property
    def estimated_duration(self) -> float:
        words_sec = self.word_count / 2.4  # ~2.4 words/sec speaking pace
        pauses = sum(s.pause_after for s in self.talk_scenes)
        cards = sum(
            s.duration
            for s in self.scenes
            if isinstance(s, (CardScene, SilentScene, AdScene))
        )
        end_card = self.end_card.duration if self.end_card else 0
        return words_sec + pauses + cards + end_card


class AdConcept(BaseModel):
    name: str
    tagline: str = ""
    description: str = ""
    style: Literal["infomercial", "luxury", "tech", "absurdist"] = "infomercial"
    voiceover_script: str = ""
    text_overlays: list[str] = Field(default_factory=list)
    duration: float = 12.0

    @classmethod
    def load(cls, path: str | Path) -> AdConcept:
        path = Path(path)
        with open(path) as f:
            data = yaml.safe_load(f)
        return cls.model_validate(data)


class SceneManifestEntry(BaseModel):
    scene_id: str
    file: str
    content_hash: str
    duration: float = 0.0
    cost_usd: float = 0.0
    engine: str = "heygen"


class RenderManifest(BaseModel):
    episode: str
    show: str
    scenes: list[SceneManifestEntry] = Field(default_factory=list)
    total_cost_usd: float = 0.0
    total_duration: float = 0.0

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            yaml.dump(self.model_dump(), f, default_flow_style=False)

    @classmethod
    def load(cls, path: str | Path) -> RenderManifest:
        path = Path(path)
        with open(path) as f:
            data = yaml.safe_load(f)
        return cls.model_validate(data)


class PublishEntry(BaseModel):
    platform: str
    url: str = ""
    published_at: str = ""
    status: str = "pending"


class PublishManifest(BaseModel):
    episode: str
    entries: list[PublishEntry] = Field(default_factory=list)

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            yaml.dump(self.model_dump(), f, default_flow_style=False)
