"""Jingle generation using Replicate MusicGen."""

from __future__ import annotations

import logging
import os
from pathlib import Path

import replicate

from broadside.config import BroadsideConfig
from broadside.ads.scriptgen import AdScript

logger = logging.getLogger(__name__)


def generate_jingle(
    config: BroadsideConfig,
    script: AdScript,
    duration: float = 10.0,
) -> Path:
    """Generate a cheesy jingle for a parody ad.

    Uses Replicate to run MusicGen for short instrumental jingles.

    Args:
        config: Broadside configuration with ads.music_model.
        script: Ad script (used for naming output).
        duration: Jingle duration in seconds (default 10).

    Returns:
        Path to generated jingle WAV file.

    Raises:
        EnvironmentError: If REPLICATE_API_TOKEN is not set.
    """
    api_token = os.environ.get("REPLICATE_API_TOKEN")
    if not api_token:
        raise EnvironmentError(
            "REPLICATE_API_TOKEN environment variable is required "
            "for jingle generation."
        )

    output_dir = Path("ads/rendered") / script.concept_name
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / "jingle.wav"

    model = config.ads.music_model
    prompt = (
        "upbeat infomercial jingle, cheesy synthesizer, "
        "1990s commercial music"
    )

    logger.info(
        "Generating jingle for '%s' (%.1fs) with model '%s'",
        script.concept_name,
        duration,
        model,
    )

    import time
    time.sleep(12)  # respect rate limits for low-credit accounts

    client = replicate.Client(api_token=api_token)

    # Resolve latest version for models that require it
    model_ref = model
    try:
        model_obj = client.models.get(model)
        if model_obj.latest_version:
            model_ref = f"{model}:{model_obj.latest_version.id}"
    except Exception:
        pass  # fall back to bare model name

    output = client.run(
        model_ref,
        input={
            "prompt": prompt,
            "duration": int(duration),
        },
    )

    # MusicGen returns a URL to the generated audio
    if hasattr(output, "read"):
        audio_bytes = output.read()
    elif isinstance(output, str):
        import httpx

        resp = httpx.get(output)
        resp.raise_for_status()
        audio_bytes = resp.content
    elif isinstance(output, list) and len(output) > 0:
        item = output[0]
        if hasattr(item, "read"):
            audio_bytes = item.read()
        else:
            import httpx

            resp = httpx.get(str(item))
            resp.raise_for_status()
            audio_bytes = resp.content
    else:
        raise RuntimeError(
            f"Unexpected Replicate output type: {type(output)}"
        )

    out_path.write_bytes(audio_bytes)
    logger.info("Saved jingle to %s", out_path)
    return out_path
