"""Voiceover generation using ElevenLabs."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from elevenlabs import ElevenLabs

from broadside.config import BroadsideConfig
from broadside.ads.scriptgen import AdScript

logger = logging.getLogger(__name__)


def generate_voiceover(
    config: BroadsideConfig,
    script: AdScript,
) -> Path:
    """Generate dramatic announcer voiceover for a parody ad.

    Uses ElevenLabs text-to-speech with the configured voice ID.

    Args:
        config: Broadside configuration with ads.voice_id.
        script: Ad script containing voiceover text.

    Returns:
        Path to generated voiceover MP3 file.

    Raises:
        EnvironmentError: If ELEVENLABS_API_KEY is not set.
        ValueError: If no voice_id is configured.
    """
    api_key = os.environ.get("ELEVENLABS_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "ELEVENLABS_API_KEY environment variable is required "
            "for voiceover generation."
        )

    voice_id = config.ads.voice_id
    if not voice_id:
        raise ValueError(
            "No voice_id configured in ads config. "
            "Set ads.voice_id in config.yaml."
        )

    output_dir = Path("ads/rendered") / script.concept_name
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / "voiceover.mp3"

    logger.info(
        "Generating voiceover for '%s' with voice '%s'",
        script.concept_name,
        voice_id,
    )

    client = ElevenLabs(api_key=api_key)

    audio_generator = client.text_to_speech.convert(
        voice_id=voice_id,
        text=script.voiceover_text,
        model_id="eleven_multilingual_v2",
    )

    # Write audio chunks to file
    with open(out_path, "wb") as f:
        for chunk in audio_generator:
            f.write(chunk)

    logger.info("Saved voiceover to %s", out_path)
    return out_path
