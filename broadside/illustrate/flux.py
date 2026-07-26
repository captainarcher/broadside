"""Illustration generation using Replicate Flux 2 Pro."""

from __future__ import annotations

import logging
import os
from pathlib import Path

import replicate

from broadside.config import BroadsideConfig
from broadside.schema import Episode

logger = logging.getLogger(__name__)


def _build_scene_prompt(style_prefix: str, scene_text: str) -> str:
    """Build an illustration prompt from style prefix and scene content.

    Extracts the core subject from scene text and combines with the
    configured style prefix for consistent visual output.
    """
    # Truncate very long scene text to keep prompts focused
    max_chars = 300
    description = scene_text.strip()
    if len(description) > max_chars:
        description = description[:max_chars].rsplit(" ", 1)[0] + "..."

    return f"{style_prefix}. Scene: {description}"


def generate_illustrations(
    config: BroadsideConfig,
    episode: Episode,
) -> list[Path]:
    """Generate 2-3 editorial illustrations for an episode.

    Uses Replicate's Flux 2 Pro model to create illustrations based on
    talk scene content combined with the configured style prefix.

    Args:
        config: Broadside configuration with illustration settings.
        episode: Episode containing scenes to illustrate.

    Returns:
        List of paths to generated illustration images.

    Raises:
        EnvironmentError: If REPLICATE_API_TOKEN is not set.
        ValueError: If episode has no talk scenes.
    """
    api_token = os.environ.get("REPLICATE_API_TOKEN")
    if not api_token:
        raise EnvironmentError(
            "REPLICATE_API_TOKEN environment variable is required "
            "for illustration generation."
        )

    talk_scenes = episode.talk_scenes
    if not talk_scenes:
        raise ValueError(
            f"Episode '{episode.episode}' has no talk scenes to illustrate."
        )

    # Select 2-3 scenes spread across the episode for visual variety
    scene_count = min(3, len(talk_scenes))
    if len(talk_scenes) <= 3:
        selected = talk_scenes[:scene_count]
    else:
        # Pick scenes evenly distributed: beginning, middle, end
        indices = [
            0,
            len(talk_scenes) // 2,
            len(talk_scenes) - 1,
        ]
        selected = [talk_scenes[i] for i in indices[:scene_count]]

    # Determine aspect ratio from show config
    try:
        show_config = config.get_show(episode.show)
        aspect_ratio = show_config.aspect_ratio
    except ValueError:
        # Fallback to 9:16 if show not configured
        aspect_ratio = "9:16"

    # Prepare output directory
    output_dir = Path("assets/illustrations") / episode.episode
    output_dir.mkdir(parents=True, exist_ok=True)

    style_prefix = config.illustrations.style_prefix
    model = config.illustrations.model
    generated: list[Path] = []

    client = replicate.Client(api_token=api_token)

    for i, scene in enumerate(selected):
        prompt = _build_scene_prompt(style_prefix, scene.text)
        logger.info(
            "Generating illustration %d/%d for scene '%s'",
            i + 1,
            len(selected),
            scene.id,
        )

        output = client.run(
            model,
            input={
                "prompt": prompt,
                "aspect_ratio": aspect_ratio,
                "num_inference_steps": 28,
                "guidance_scale": 3.5,
            },
        )

        # Replicate returns a FileOutput or URL; read the bytes
        if hasattr(output, "read"):
            image_bytes = output.read()
        elif isinstance(output, list) and len(output) > 0:
            item = output[0]
            if hasattr(item, "read"):
                image_bytes = item.read()
            else:
                import httpx

                resp = httpx.get(str(item))
                resp.raise_for_status()
                image_bytes = resp.content
        elif isinstance(output, str):
            import httpx

            resp = httpx.get(output)
            resp.raise_for_status()
            image_bytes = resp.content
        else:
            raise RuntimeError(
                f"Unexpected Replicate output type: {type(output)}"
            )

        out_path = output_dir / f"illustration-{i + 1}.png"
        out_path.write_bytes(image_bytes)
        logger.info("Saved illustration to %s", out_path)
        generated.append(out_path)

    return generated
