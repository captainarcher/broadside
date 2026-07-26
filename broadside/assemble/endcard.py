"""End card video generation using ffmpeg.

Creates a short video clip with solid background color, centered
wordmark image, and text line below using ffmpeg filters.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

from ..config import ShowConfig

logger = logging.getLogger(__name__)


class EndCardError(Exception):
    """Raised when end card generation fails."""


def generate_endcard(
    show_config: ShowConfig,
    duration: float,
    output_path: Path,
) -> Path:
    """Generate an end card video clip.

    Creates a video with:
    - Solid background in show's background_color
    - Wordmark image centered in upper third
    - Brand text line centered below wordmark

    Args:
        show_config: Show configuration with brand assets and colors.
        duration: Duration of the end card in seconds.
        output_path: Where to write the output MP4.

    Returns:
        Path to the generated end card MP4.

    Raises:
        EndCardError: If ffmpeg fails or assets are missing.
    """
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise EndCardError("ffmpeg not found on PATH")

    w, h = show_config.dimensions
    bg_color = show_config.background_color.lstrip("#")
    wordmark_path = Path(show_config.brand.wordmark)
    end_text = show_config.brand.end_text

    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Build the filter complex
    filters: list[str] = []

    if wordmark_path.exists():
        # Color background + wordmark overlay + drawtext
        input_args = [
            "-f", "lavfi",
            "-t", str(duration),
            "-i", f"color=c={bg_color}:s={w}x{h}:r=30",
            "-i", str(wordmark_path),
        ]
        # Position wordmark centered in upper third
        wordmark_y = f"(H-h)/3"
        filters.append(
            f"[1:v]scale=-1:{h // 6}[wm]"
        )
        filters.append(
            f"[0:v][wm]overlay=(W-w)/2:{wordmark_y}[bg_wm]"
        )
        # Add text below wordmark
        text_y = f"(h*2/3)"
        # Escape special characters for drawtext
        escaped_text = end_text.replace("'", "\\'").replace(":", "\\:")
        filters.append(
            f"[bg_wm]drawtext=text='{escaped_text}':"
            f"fontsize={show_config.caption.size - 8}:"
            f"fontcolor=white:"
            f"x=(w-text_w)/2:"
            f"y={text_y}[vout]"
        )
    else:
        # No wordmark image, just background + text
        logger.warning("Wordmark not found at %s, generating text-only end card", wordmark_path)
        input_args = [
            "-f", "lavfi",
            "-t", str(duration),
            "-i", f"color=c={bg_color}:s={w}x{h}:r=30",
        ]
        escaped_text = end_text.replace("'", "\\'").replace(":", "\\:")
        filters.append(
            f"[0:v]drawtext=text='{escaped_text}':"
            f"fontsize={show_config.caption.size}:"
            f"fontcolor=white:"
            f"x=(w-text_w)/2:"
            f"y=(h-text_h)/2[vout]"
        )

    filter_complex = ";\n".join(filters)

    # Generate silent audio track
    cmd = [
        ffmpeg, "-y",
        *input_args,
        "-f", "lavfi", "-t", str(duration),
        "-i", "anullsrc=r=48000:cl=stereo",
        "-filter_complex", filter_complex,
        "-map", "[vout]",
        "-map", f"{len(input_args) // 2}:a",  # map the anullsrc audio
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "18",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "128k",
        "-shortest",
        "-movflags", "+faststart",
        str(output_path),
    ]

    logger.debug("Generating end card: %s", " ".join(cmd))
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        raise EndCardError(f"End card generation failed: {result.stderr}")

    logger.info("Generated end card: %s (%.1fs)", output_path, duration)
    return output_path
