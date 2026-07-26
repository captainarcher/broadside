"""Parody ad generation subsystem."""

from __future__ import annotations

import logging
import random
from pathlib import Path

from broadside.config import BroadsideConfig
from broadside.schema import AdConcept

logger = logging.getLogger(__name__)


def generate_parody_ad(
    config: BroadsideConfig,
    concept: AdConcept | None = None,
    random_concept: bool = False,
) -> Path:
    """Generate a complete parody ad from concept to final video.

    Pipeline: scriptgen -> assets -> voice -> music -> compose

    Args:
        config: Broadside configuration.
        concept: Specific AdConcept to produce. If None, must set
            random_concept=True.
        random_concept: If True, pick a random YAML from the
            configured concept_bank directory.

    Returns:
        Path to the final rendered MP4.

    Raises:
        ValueError: If neither concept nor random_concept is provided.
        FileNotFoundError: If concept_bank directory is empty or missing.
    """
    if concept is None and not random_concept:
        raise ValueError(
            "Either provide a concept or set random_concept=True."
        )

    if concept is None:
        concept = _pick_random_concept(config)

    # Import here to avoid circular imports at module level
    from broadside.ads.scriptgen import generate_ad_script
    from broadside.ads.assets import generate_product_images
    from broadside.ads.voice import generate_voiceover
    from broadside.ads.music import generate_jingle
    from broadside.ads.compose import compose_ad

    logger.info("Starting parody ad pipeline for '%s'", concept.name)

    # 1. Generate full script from concept
    script = generate_ad_script(config, concept)

    # 2. Generate product images
    images = generate_product_images(config, script)

    # 3. Generate voiceover
    voiceover = generate_voiceover(config, script)

    # 4. Generate jingle
    jingle = generate_jingle(config, script, duration=script.duration)

    # 5. Compose final video
    final_path = compose_ad(config, script, images, voiceover, jingle)

    logger.info("Parody ad complete: %s", final_path)
    return final_path


def _pick_random_concept(config: BroadsideConfig) -> AdConcept:
    """Pick a random AdConcept YAML from the concept bank directory."""
    concept_dir = Path(config.ads.concept_bank)
    if not concept_dir.exists():
        raise FileNotFoundError(
            f"Concept bank directory not found: {concept_dir}"
        )

    yaml_files = list(concept_dir.glob("*.yaml")) + list(
        concept_dir.glob("*.yml")
    )
    if not yaml_files:
        raise FileNotFoundError(
            f"No YAML files found in concept bank: {concept_dir}"
        )

    chosen = random.choice(yaml_files)
    logger.info("Randomly selected concept: %s", chosen.name)
    return AdConcept.load(chosen)


__all__ = ["generate_parody_ad"]
