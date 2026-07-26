"""Pydantic configuration models for Broadside."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field


class CaptionConfig(BaseModel):
    font: str = "assets/fonts/condensed-bold.ttf"
    size: int = 48
    y_position: float = 0.75
    highlight_color: str = "#E63946"


class BrandConfig(BaseModel):
    wordmark: str = "assets/brand/bs-wordmark.png"
    end_text: str = "@thatsthebs · New every weekday"


class ShowConfig(BaseModel):
    avatar_id: str
    voice_id: str
    aspect_ratio: Literal["9:16", "16:9"] = "9:16"
    dimensions: tuple[int, int] = (1080, 1920)
    engine: Literal["avatar_iii", "avatar_iv", "avatar_v"] = "avatar_iv"
    cost_per_sec: float = 0.05
    background_color: str = "#0D1B2A"
    caption: CaptionConfig = CaptionConfig()
    brand: BrandConfig = BrandConfig()


class BudgetConfig(BaseModel):
    max_batch_usd: float = 25.0
    max_weekly_usd: float = 40.0


class NotifyWebhook(BaseModel):
    type: Literal["webhook"] = "webhook"
    url: str


class NotifySmtp(BaseModel):
    type: Literal["smtp"] = "smtp"
    host: str = "smtp.gmail.com"
    port: int = 587
    to: str = ""


class NotifyOsascript(BaseModel):
    type: Literal["osascript"] = "osascript"


NotifyConfig = NotifyOsascript | NotifyWebhook | NotifySmtp


class RedditSourceConfig(BaseModel):
    subreddits: list[str] = ["nottheonion", "technology", "science", "offbeat"]


class HackerNewsSourceConfig(BaseModel):
    top_n: int = 200


class GoogleNewsSourceConfig(BaseModel):
    topics: list[str] = ["technology", "business", "science", "entertainment"]


class NewsDataSourceConfig(BaseModel):
    categories: list[str] = ["technology", "business", "science", "entertainment"]


class NewsSourcesConfig(BaseModel):
    reddit: RedditSourceConfig = RedditSourceConfig()
    hackernews: HackerNewsSourceConfig = HackerNewsSourceConfig()
    google_news: GoogleNewsSourceConfig = GoogleNewsSourceConfig()
    newsdata: NewsDataSourceConfig = NewsDataSourceConfig()


class PoliticalFilterConfig(BaseModel):
    keywords_file: str = "config/political-keywords.txt"
    llm_classification: bool = True


class NewsConfig(BaseModel):
    sources: NewsSourcesConfig = NewsSourcesConfig()
    political_filter: PoliticalFilterConfig = PoliticalFilterConfig()


class ComedyConfig(BaseModel):
    model_angles: str = "anthropic/claude-sonnet-4.6"
    model_jokes: str = "anthropic/claude-sonnet-4.6"
    model_assembly: str = "anthropic/claude-sonnet-4.6"
    model_polish: str = "anthropic/claude-opus-4.6"
    character_sheet: str = "config/character-sheet.yaml"
    example_bank: str = "examples/"
    duration_target: int = 75


class IllustrationConfig(BaseModel):
    model: str = "black-forest-labs/flux-2-pro"
    style_references: str = "assets/style-references/"
    style_prefix: str = (
        "Editorial courtroom sketch style, colored pencil and charcoal on cream "
        "textured paper, loose expressive strokes, muted earth tones with selective "
        "color accents, dramatic chiaroscuro lighting"
    )


class AdsConfig(BaseModel):
    voice_provider: Literal["elevenlabs", "heygen"] = "elevenlabs"
    voice_id: str = ""
    music_model: str = "meta/musicgen"
    vhs_filter: bool = True
    concept_bank: str = "ads/concepts/"


class YouTubePublishConfig(BaseModel):
    privacy: Literal["public", "private", "unlisted"] = "public"
    category_id: str = "24"
    made_for_kids: bool = False
    contains_synthetic_media: bool = True


class InstagramPublishConfig(BaseModel):
    browser: Literal["headed", "headless"] = "headed"


class TikTokPublishConfig(BaseModel):
    browser: Literal["headed", "headless"] = "headed"
    default_visibility: str = "public"


class PublishingConfig(BaseModel):
    youtube: YouTubePublishConfig = YouTubePublishConfig()
    instagram: InstagramPublishConfig = InstagramPublishConfig()
    tiktok: TikTokPublishConfig = TikTokPublishConfig()


class BroadsideConfig(BaseModel):
    shows: dict[str, ShowConfig] = Field(default_factory=dict)
    budget: BudgetConfig = BudgetConfig()
    notify: list[NotifyConfig] = Field(default_factory=list)
    news: NewsConfig = NewsConfig()
    comedy: ComedyConfig = ComedyConfig()
    illustrations: IllustrationConfig = IllustrationConfig()
    ads: AdsConfig = AdsConfig()
    publishing: PublishingConfig = PublishingConfig()

    @classmethod
    def load(cls, path: str | Path = "config/config.yaml") -> BroadsideConfig:
        path = Path(path)
        if not path.exists():
            return cls()
        with open(path) as f:
            data = yaml.safe_load(f) or {}
        return cls.model_validate(data)

    def get_show(self, show_name: str) -> ShowConfig:
        if show_name not in self.shows:
            available = ", ".join(self.shows.keys()) or "(none configured)"
            raise ValueError(
                f"Unknown show '{show_name}'. Available: {available}"
            )
        return self.shows[show_name]
