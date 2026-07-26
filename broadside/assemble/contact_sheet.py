"""Contact sheet (thumbnail grid) generation from final video.

Extracts evenly-spaced keyframes and tiles them into a grid
using ffmpeg filters.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


class ContactSheetError(Exception):
    """Raised when contact sheet generation fails."""


def generate_contact_sheet(
    video_path: Path,
    output_path: Path,
    cols: int = 4,
    rows: int = 3,
) -> Path:
    """Generate a contact sheet (thumbnail grid) from a video.

    Extracts evenly-spaced frames from the video and tiles them
    into a grid PNG.

    Args:
        video_path: Path to the source video.
        output_path: Path for the output PNG.
        cols: Number of columns in the grid.
        rows: Number of rows in the grid.

    Returns:
        Path to the generated contact sheet PNG.

    Raises:
        ContactSheetError: If ffmpeg fails.
    """
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg:
        raise ContactSheetError("ffmpeg not found on PATH")
    if not ffprobe:
        raise ContactSheetError("ffprobe not found on PATH")

    if not video_path.exists():
        raise ContactSheetError(f"Video not found: {video_path}")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    total_frames = cols * rows

    # Get total frame count from video
    result = subprocess.run(
        [
            ffprobe,
            "-v", "error",
            "-count_frames",
            "-select_streams", "v:0",
            "-show_entries", "stream=nb_read_frames",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(video_path),
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )

    if result.returncode != 0 or not result.stdout.strip().isdigit():
        # Fallback: estimate from duration and assume 30fps
        dur_result = subprocess.run(
            [
                ffprobe,
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(video_path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if dur_result.returncode != 0:
            raise ContactSheetError(f"Cannot determine video properties: {dur_result.stderr}")
        duration = float(dur_result.stdout.strip())
        nb_frames = int(duration * 30)
    else:
        nb_frames = int(result.stdout.strip())

    # Calculate frame selection interval
    # Pick every Nth frame to get ~total_frames evenly distributed
    frame_interval = max(1, nb_frames // total_frames)

    # Use select filter to pick frames, then tile them
    select_expr = f"not(mod(n\\,{frame_interval}))"

    cmd = [
        ffmpeg, "-y",
        "-i", str(video_path),
        "-vf", (
            f"select='{select_expr}',"
            f"scale=320:-1,"
            f"tile={cols}x{rows}"
        ),
        "-frames:v", "1",
        "-qscale:v", "2",
        str(output_path),
    ]

    logger.debug("Generating contact sheet: %s", " ".join(cmd))
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if proc.returncode != 0:
        raise ContactSheetError(f"Contact sheet generation failed: {proc.stderr}")

    logger.info("Generated contact sheet: %s (%dx%d grid)", output_path, cols, rows)
    return output_path
