"""Product image generation using Replicate Flux 2 Pro."""

from __future__ import annotations

import logging
import os
from pathlib import Path

import replicate

from broadside.config import BroadsideConfig
from broadside.ads.scriptgen import AdScript

logger = logging.getLogger(__name__)

# Style guidance per ad style
_STYLE_GUIDANCE = {
    "infomercial": (
        "1990s infomercial product photography, bright studio lighting, "
        "white seamless background, dramatic product angles, cheesy "
        "commercial aesthetic, bold saturated colors"
    ),
    "luxury": (
        "luxury product photography, dark moody lighting, marble surface, "
        "gold accents, premium feel, magazine advertisement quality"
    ),
    "tech": (
        "sleek tech product photography, minimalist white background, "
        "soft gradient lighting, Apple-style clean aesthetic, "
        "futuristic clean lines"
    ),
    "absurdist": (
        "surreal absurdist product photography, impossible objects, "
        "dreamlike composition, bright pop art colors, Tim and Eric "
        "aesthetic, deliberately uncanny"
    ),
}


def _get_style_prefix(style: str) -> str:
    """Get style guidance for a given ad style."""
    return _STYLE_GUIDANCE.get(style, _STYLE_GUIDANCE["infomercial"])


def generate_product_images(
    config: BroadsideConfig,
    script: AdScript,
) -> list[Path]:
    """Generate product images for a parody ad.

    Creates 3 images: product shot, logo, and lifestyle scene using
    Replicate's Flux 2 Pro model.

    Args:
        config: Broadside configuration with illustration settings.
        script: Ad script containing visual descriptions and style.

    Returns:
        List of 3 paths to generated images.

    Raises:
        EnvironmentError: If REPLICATE_API_TOKEN is not set.
    """
    api_token = os.environ.get("REPLICATE_API_TOKEN")
    if not api_token:
        raise EnvironmentError(
            "REPLICATE_API_TOKEN environment variable is required "
            "for product image generation."
        )

    output_dir = Path("ads/rendered") / script.concept_name / "images"
    output_dir.mkdir(parents=True, exist_ok=True)

    style_prefix = _get_style_prefix(script.style)
    model = config.illustrations.model

    # Build prompts for 3 image types
    image_specs = [
        ("product", "product shot"),
        ("logo", "logo"),
        ("lifestyle", "lifestyle scene"),
    ]

    # Use visual descriptions from script if available
    prompts: list[tuple[str, str]] = []
    for i, (filename, fallback_type) in enumerate(image_specs):
        if i < len(script.visual_descriptions):
            desc = script.visual_descriptions[i]
        else:
            desc = f"{fallback_type} of {script.product_name}"
        prompt = f"{style_prefix}. {desc}"
        prompts.append((filename, prompt))

    client = replicate.Client(api_token=api_token)
    generated: list[Path] = []

    import time
    for i, (filename, prompt) in enumerate(prompts):
        if i > 0:
            time.sleep(12)  # respect rate limits for low-credit accounts
        logger.info(
            "Generating %s image for '%s'",
            filename,
            script.concept_name,
        )

        output = client.run(
            model,
            input={
                "prompt": prompt,
                "aspect_ratio": "16:9",
                "num_inference_steps": 28,
                "guidance_scale": 3.5,
            },
        )

        # Handle various Replicate output formats
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

        out_path = output_dir / f"{filename}.png"
        out_path.write_bytes(image_bytes)
        logger.info("Saved %s image to %s", filename, out_path)
        generated.append(out_path)

    return generated
