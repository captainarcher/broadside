"""Ad script generation using Claude API."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from broadside.config import BroadsideConfig
from broadside.llm import chat
from broadside.schema import AdConcept

logger = logging.getLogger(__name__)


@dataclass
class AdScript:
    """Complete ad script with all fields needed for production."""

    concept_name: str
    product_name: str
    tagline: str
    voiceover_text: str
    text_overlays: list[str] = field(default_factory=list)
    visual_descriptions: list[str] = field(default_factory=list)
    style: str = "infomercial"
    duration: float = 12.0


_SYSTEM_PROMPT = """\
You are a comedy writer for a satirical news show. You write parody \
advertisement scripts in the style of late-night infomercials, absurdist \
product ads, and over-the-top commercial parodies.

Given a product concept, generate a complete ad script. Return valid JSON \
with these exact keys:
- product_name: string (the fake product name)
- tagline: string (catchy slogan)
- voiceover_text: string (dramatic announcer voiceover, 2-4 sentences)
- text_overlays: list of strings (3-5 text overlays to show on screen)
- visual_descriptions: list of strings (3 image descriptions for product shots)
"""


def generate_ad_script(
    config: BroadsideConfig,
    concept: AdConcept,
) -> AdScript:
    """Generate a full ad script from an ad concept.

    If the concept already has a voiceover_script filled in, uses it
    directly. Otherwise calls Claude to flesh out the concept.

    Args:
        config: Broadside configuration.
        concept: Ad concept with name, description, style.

    Returns:
        Complete AdScript ready for production.

    Raises:
        EnvironmentError: If OPENROUTER_API_KEY is not set.
    """
    # If concept already has a full voiceover script, use it directly
    if concept.voiceover_script.strip():
        return AdScript(
            concept_name=concept.name,
            product_name=concept.name,
            tagline=concept.tagline or f"The {concept.name} Revolution",
            voiceover_text=concept.voiceover_script,
            text_overlays=concept.text_overlays or [
                concept.name,
                concept.tagline or "Order Now!",
                "CALL NOW!",
            ],
            visual_descriptions=[
                f"Product shot of {concept.name}, {concept.style} style",
                f"Logo for {concept.name}, bold dramatic text",
                f"Lifestyle scene featuring {concept.name}",
            ],
            style=concept.style,
            duration=concept.duration,
        )

    user_prompt = (
        f"Product concept: {concept.name}\n"
        f"Description: {concept.description}\n"
        f"Style: {concept.style}\n"
        f"Duration: {concept.duration} seconds\n"
    )
    if concept.tagline:
        user_prompt += f"Tagline suggestion: {concept.tagline}\n"

    logger.info("Generating ad script for concept '%s'", concept.name)

    raw_text = chat(
        model=config.comedy.model_jokes,
        messages=[{"role": "user", "content": user_prompt}],
        system=_SYSTEM_PROMPT,
        max_tokens=1024,
    )

    # Parse JSON from response (handle markdown code fences)
    json_text = raw_text.strip()
    if json_text.startswith("```"):
        # Strip code fences
        lines = json_text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        json_text = "\n".join(lines)

    data = json.loads(json_text)

    return AdScript(
        concept_name=concept.name,
        product_name=data.get("product_name", concept.name),
        tagline=data.get("tagline", concept.tagline or ""),
        voiceover_text=data.get("voiceover_text", ""),
        text_overlays=data.get("text_overlays", ["Order Now!", "CALL NOW!"]),
        visual_descriptions=data.get("visual_descriptions", []),
        style=concept.style,
        duration=concept.duration,
    )
