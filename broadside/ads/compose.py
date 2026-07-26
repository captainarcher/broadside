"""FFmpeg-based ad composition with Ken Burns, text overlays, and VHS effects."""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

from broadside.config import BroadsideConfig
from broadside.ads.scriptgen import AdScript

logger = logging.getLogger(__name__)


def _check_ffmpeg() -> str:
    """Verify ffmpeg is available and return its path."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError(
            "ffmpeg not found on PATH. Install ffmpeg to compose ads."
        )
    return ffmpeg


def _build_ken_burns_filter(
    image_count: int,
    duration_per_image: float,
    fade_ms: int = 100,
) -> str:
    """Build ffmpeg filter for Ken Burns (slow zoom) on image slides.

    Each image gets a slow zoom-in effect with crossfade transitions.
    """
    fade_sec = fade_ms / 1000.0
    filters: list[str] = []

    for i in range(image_count):
        # Scale up to allow zoom headroom, then apply slow zoom via zoompan
        # zoompan: zoom from 1.0 to 1.15 over the duration
        filters.append(
            f"[{i}:v]scale=1920:1080,setsar=1,"
            f"zoompan=z='min(zoom+0.0015,1.15)':x='iw/2-(iw/zoom/2)':"
            f"y='ih/2-(ih/zoom/2)':d={int(duration_per_image * 25)}:"
            f"s=1920x1080:fps=25,"
            f"setpts=PTS-STARTPTS[v{i}]"
        )

    # Concatenate with crossfade transitions
    if image_count == 1:
        return ";".join(filters) + f";[v0]format=yuv420p[outv]"

    result = ";".join(filters)

    # Chain crossfades between consecutive clips
    prev = "v0"
    for i in range(1, image_count):
        offset = i * duration_per_image - fade_sec * i
        out_label = f"cf{i}" if i < image_count - 1 else "merged"
        result += (
            f";[{prev}][v{i}]xfade=transition=fade:"
            f"duration={fade_sec}:offset={offset:.3f}[{out_label}]"
        )
        prev = out_label

    result += f";[merged]format=yuv420p[outv]"
    return result


def _build_text_overlay_filter(
    overlays: list[str],
    total_duration: float,
) -> str:
    """Build drawtext filters for text overlays.

    Distributes text overlays evenly across the video duration.
    """
    if not overlays:
        return ""

    filters: list[str] = []
    interval = total_duration / len(overlays)

    for i, text in enumerate(overlays):
        start = i * interval
        end = start + interval
        # Escape special characters for ffmpeg drawtext
        escaped = (
            text.replace("\\", "\\\\")
            .replace("'", "\\'")
            .replace(":", "\\:")
            .replace("[", "\\[")
            .replace("]", "\\]")
        )
        filters.append(
            f"drawtext=text='{escaped}':"
            f"fontsize=48:fontcolor=white:"
            f"borderw=3:bordercolor=black:"
            f"x=(w-text_w)/2:y=h-h/4:"
            f"enable='between(t,{start:.2f},{end:.2f})'"
        )

    return ",".join(filters)


def _build_vhs_filter() -> str:
    """Build VHS degradation filter (scanlines, color shift, blur)."""
    return (
        # Slight gaussian blur for VHS softness
        "gblur=sigma=0.8,"
        # Color channel shift for chromatic aberration
        "colorchannelmixer="
        "rr=0.95:rg=0.05:rb=0.0:"
        "gr=0.0:gg=0.95:gb=0.05:"
        "br=0.05:bg=0.0:bb=0.95,"
        # Scanline overlay via noise + blend
        "noise=alls=15:allf=t"
    )


def compose_ad(
    config: BroadsideConfig,
    script: AdScript,
    images: list[Path],
    voiceover: Path,
    jingle: Path,
) -> Path:
    """Compose final ad video from images, voiceover, and jingle.

    Applies Ken Burns zoom on images, text overlays, mixed audio
    (voiceover at full volume, jingle ducked -20dB), and optional
    VHS degradation filter.

    Args:
        config: Broadside configuration.
        script: Ad script with text overlays and metadata.
        images: List of product image paths.
        voiceover: Path to voiceover MP3.
        jingle: Path to jingle WAV.

    Returns:
        Path to final composed MP4.

    Raises:
        RuntimeError: If ffmpeg is not found or encoding fails.
    """
    ffmpeg = _check_ffmpeg()

    output_dir = Path("ads/rendered") / script.concept_name
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / "final.mp4"

    # Use voiceover duration if longer than configured duration
    total_duration = script.duration
    try:
        import subprocess as _sp
        probe = _sp.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(voiceover)],
            capture_output=True, text=True, timeout=10,
        )
        vo_duration = float(probe.stdout.strip())
        if vo_duration > total_duration:
            logger.info("Extending ad duration to match voiceover: %.1fs -> %.1fs", total_duration, vo_duration + 1.0)
            total_duration = vo_duration + 1.0  # add 1s buffer
    except Exception:
        pass
    duration_per_image = total_duration / max(len(images), 1)

    # Build input arguments
    cmd: list[str] = [ffmpeg, "-y"]

    # Add image inputs with loop
    for img in images:
        cmd.extend(["-loop", "1", "-t", f"{duration_per_image:.2f}", "-i", str(img)])

    # Add audio inputs
    cmd.extend(["-i", str(voiceover)])
    cmd.extend(["-i", str(jingle)])

    vo_index = len(images)
    jingle_index = len(images) + 1

    # Add applause/laugh track if available (SNL-style bookend)
    applause_path = Path("assets/sfx/applause.wav")
    has_applause = applause_path.exists()
    if has_applause:
        cmd.extend(["-i", str(applause_path)])
        applause_index = len(images) + 2
    else:
        applause_index = -1

    # Build video filter chain
    video_filter = _build_ken_burns_filter(
        len(images), duration_per_image, fade_ms=100
    )

    # Add text overlays (requires ffmpeg built with libfreetype/drawtext)
    final_video_label = "outv"
    try:
        import subprocess as _sp
        _check = _sp.run(["ffmpeg", "-filters"], capture_output=True, text=True)
        has_drawtext = "drawtext" in _check.stdout
    except Exception:
        has_drawtext = False

    if has_drawtext:
        text_filter = _build_text_overlay_filter(
            script.text_overlays, total_duration
        )
        if text_filter:
            video_filter += f";[outv]{text_filter}[textv]"
            final_video_label = "textv"
    else:
        logger.warning("drawtext filter not available — skipping text overlays. "
                       "Reinstall ffmpeg with freetype support for text overlays.")

    # Add VHS filter if enabled
    if config.ads.vhs_filter:
        vhs = _build_vhs_filter()
        video_filter += f";[{final_video_label}]{vhs}[vhsv]"
        final_video_label = "vhsv"

    # Audio: mix voiceover at full volume, jingle ducked -20dB
    # Add applause fading in over the last 4 seconds (SNL-style bookend)
    if has_applause:
        applause_start = max(0, total_duration - 5.0)
        audio_filter = (
            f"[{jingle_index}:a]volume=-20dB[jingle_ducked];"
            f"[{applause_index}:a]adelay={int(applause_start * 1000)}|{int(applause_start * 1000)},"
            f"afade=t=in:st=0:d=1.5,volume=-6dB[applause_delayed];"
            f"[{vo_index}:a][jingle_ducked][applause_delayed]amix=inputs=3:"
            f"duration=longest:normalize=0[outa]"
        )
    else:
        audio_filter = (
            f"[{jingle_index}:a]volume=-20dB[jingle_ducked];"
            f"[{vo_index}:a][jingle_ducked]amix=inputs=2:"
            f"duration=longest:normalize=0[outa]"
        )

    full_filter = f"{video_filter};{audio_filter}"

    cmd.extend([
        "-filter_complex", full_filter,
        "-map", f"[{final_video_label}]",
        "-map", "[outa]",
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "23",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "192k",
        "-t", f"{total_duration:.2f}",
        "-shortest",
        str(out_path),
    ])

    logger.info("Composing ad video for '%s'", script.concept_name)
    logger.debug("FFmpeg command: %s", " ".join(cmd))

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=120,
    )

    if result.returncode != 0:
        logger.error("FFmpeg stderr:\n%s", result.stderr)
        raise RuntimeError(
            f"FFmpeg failed with exit code {result.returncode}: "
            f"{result.stderr[:500]}"
        )

    logger.info("Saved final ad to %s", out_path)
    return out_path
