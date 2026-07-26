"""Video assembly subsystem for Broadside.

Provides `assemble_episode` as the main entry point for assembling
rendered scenes into a final video with captions, end card, and
contact sheet.

Supports two engines:
- "descript": Cloud-based assembly via Descript API
- "ffmpeg": Local deterministic assembly via ffmpeg
- "auto": Try Descript first, fall back to ffmpeg on failure
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

import httpx

from ..config import BroadsideConfig, ShowConfig
from ..schema import Episode

logger = logging.getLogger(__name__)


def _validate_ffmpeg() -> None:
    """Check that ffmpeg and ffprobe are available on PATH."""
    if not shutil.which("ffmpeg"):
        raise RuntimeError(
            "ffmpeg not found on PATH. Install ffmpeg to use the assembly pipeline."
        )
    if not shutil.which("ffprobe"):
        raise RuntimeError(
            "ffprobe not found on PATH. Install ffmpeg (includes ffprobe)."
        )


def _collect_scene_files(episode: Episode, build_dir: Path) -> dict[str, Path]:
    """Collect rendered scene file paths from the build directory."""
    scene_dir = build_dir / episode.episode
    files: dict[str, Path] = {}
    for scene in episode.scenes:
        scene_path = scene_dir / f"{scene.id}.mp4"
        if scene_path.exists():
            files[scene.id] = scene_path
    return files


def _assemble_with_descript(
    episode: Episode,
    show_config: ShowConfig,
    build_dir: Path,
    out_dir: Path,
) -> Path:
    """Assemble episode using Descript cloud API.

    Pipeline: import media -> agent for captions/Studio Sound -> publish -> download.
    """
    from .descript import (
        DescriptError,
        import_media,
        publish_project,
        run_agent,
        _get_token,
    )

    token = _get_token()
    scene_files = _collect_scene_files(episode, build_dir)
    if not scene_files:
        raise DescriptError("No scene files found to import")

    file_paths = [str(p) for p in scene_files.values()]

    # Step 1: Import media
    logger.info("Importing %d scene files to Descript", len(file_paths))
    project_id = import_media(token, file_paths)

    # Step 2: Run agent for captions and Studio Sound
    prompt = (
        "Add word-level captions to all clips. "
        "Apply Studio Sound to enhance audio quality. "
        "Remove filler words and long pauses."
    )
    run_agent(token, project_id, prompt)

    # Step 3: Publish and download
    logger.info("Publishing project %s", project_id)
    download_url = publish_project(token, project_id)

    # Download the published video
    output_path = out_dir / episode.episode / f"final-{episode.episode}.mp4"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    logger.info("Downloading published video from %s", download_url)
    with httpx.stream("GET", download_url, timeout=300, follow_redirects=True) as resp:
        resp.raise_for_status()
        with open(output_path, "wb") as f:
            for chunk in resp.iter_bytes(chunk_size=8192):
                f.write(chunk)

    logger.info("Downloaded Descript output: %s", output_path)
    return output_path


def _assemble_with_ffmpeg(
    episode: Episode,
    show_config: ShowConfig,
    build_dir: Path,
    out_dir: Path,
) -> Path:
    """Assemble episode using local ffmpeg pipeline.

    Pipeline: assemble timeline -> generate captions -> burn captions -> end card.
    """
    from .captions import burn_captions, generate_captions
    from .endcard import generate_endcard
    from .ffmpeg import assemble_timeline

    _validate_ffmpeg()

    # Step 1: Assemble the timeline
    logger.info("Assembling timeline for %s", episode.episode)
    assembled = assemble_timeline(episode, show_config, build_dir, out_dir)

    # Step 2: Generate and burn captions
    scene_files = _collect_scene_files(episode, build_dir)
    if scene_files and episode.talk_scenes:
        logger.info("Generating captions for %s", episode.episode)
        ass_path = generate_captions(episode, scene_files, show_config)

        captioned = assembled.parent / f"captioned-{episode.episode}.mp4"
        burn_captions(assembled, ass_path, captioned)

        # Replace assembled with captioned version
        assembled.unlink()
        captioned.rename(assembled)

    # Step 3: Generate end card if specified
    if episode.end_card:
        endcard_path = build_dir / episode.episode / f"endcard-{episode.episode}.mp4"
        generate_endcard(show_config, episode.end_card.duration, endcard_path)

        # Concatenate main video with end card
        concat_list = assembled.parent / "concat_list.txt"
        concat_list.write_text(
            f"file '{assembled}'\nfile '{endcard_path}'\n"
        )
        final_with_endcard = assembled.parent / f"with-endcard-{episode.episode}.mp4"

        import subprocess
        result = subprocess.run(
            [
                "ffmpeg", "-y",
                "-f", "concat", "-safe", "0",
                "-i", str(concat_list),
                "-c", "copy",
                "-movflags", "+faststart",
                str(final_with_endcard),
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            logger.error("End card concatenation failed: %s", result.stderr)
        else:
            assembled.unlink()
            final_with_endcard.rename(assembled)

        # Clean up
        concat_list.unlink(missing_ok=True)

    logger.info("FFmpeg assembly complete: %s", assembled)
    return assembled


def assemble_episode(
    config: BroadsideConfig,
    episode: Episode,
    engine: str = "auto",
    build_dir: Path = Path("build"),
    out_dir: Path = Path("out"),
) -> Path:
    """Assemble an episode from rendered scenes into a final video.

    Args:
        config: Broadside configuration.
        episode: Episode schema with scenes.
        engine: Assembly engine - "descript", "ffmpeg", or "auto".
            "auto" tries Descript first, falls back to ffmpeg.
        build_dir: Directory containing rendered scene files.
        out_dir: Output directory for final deliverables.

    Returns:
        Path to the final assembled MP4.
    """
    show_config = config.get_show(episode.show)

    if engine == "descript":
        final_video = _assemble_with_descript(episode, show_config, build_dir, out_dir)
    elif engine == "ffmpeg":
        final_video = _assemble_with_ffmpeg(episode, show_config, build_dir, out_dir)
    elif engine == "auto":
        try:
            logger.info("Attempting Descript assembly for %s", episode.episode)
            final_video = _assemble_with_descript(episode, show_config, build_dir, out_dir)
        except Exception as e:
            logger.warning("Descript assembly failed (%s), falling back to ffmpeg", e)
            final_video = _assemble_with_ffmpeg(episode, show_config, build_dir, out_dir)
    else:
        raise ValueError(f"Unknown assembly engine: {engine!r}. Use 'descript', 'ffmpeg', or 'auto'.")

    # Copy final MP4 to output location
    final_output = out_dir / episode.episode / f"final-{episode.episode}.mp4"
    final_output.parent.mkdir(parents=True, exist_ok=True)
    if final_video != final_output:
        shutil.copy2(final_video, final_output)

    # Copy caption hook text
    if episode.caption_hook:
        caption_path = out_dir / episode.episode / "caption.txt"
        caption_path.write_text(episode.caption_hook, encoding="utf-8")
        logger.info("Wrote caption hook: %s", caption_path)

    # Generate contact sheet
    from .contact_sheet import generate_contact_sheet

    sheet_path = out_dir / episode.episode / f"contact-sheet-{episode.episode}.png"
    try:
        generate_contact_sheet(final_output, sheet_path)
    except Exception as e:
        logger.warning("Contact sheet generation failed: %s", e)

    logger.info("Episode assembly complete: %s", final_output)
    return final_output
