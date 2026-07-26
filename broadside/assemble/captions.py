"""Word-by-word karaoke caption generation using faster-whisper alignment.

Generates ASS subtitle files with per-word timing where the current
word is highlighted in the show's accent color. Supports burning
subtitles into video via ffmpeg.
"""

from __future__ import annotations

import logging
import subprocess
import shutil
from pathlib import Path

from ..config import ShowConfig
from ..schema import CardScene, Episode, TalkScene

logger = logging.getLogger(__name__)


class CaptionError(Exception):
    """Raised when caption generation fails."""


def _hex_to_ass_color(hex_color: str) -> str:
    """Convert hex color (#RRGGBB) to ASS color format (&HBBGGRR&).

    ASS uses BGR order with &H prefix and & suffix.
    """
    hex_color = hex_color.lstrip("#")
    r = hex_color[0:2]
    g = hex_color[2:4]
    b = hex_color[4:6]
    return f"&H00{b}{g}{r}&"


def _generate_ass_header(show_config: ShowConfig) -> str:
    """Generate ASS file header with styles."""
    w, h = show_config.dimensions
    y_margin = int(h * (1.0 - show_config.caption.y_position))
    font_size = show_config.caption.size
    highlight_color = _hex_to_ass_color(show_config.caption.highlight_color)
    white = "&H00FFFFFF&"
    outline_color = "&H00000000&"

    return f"""[Script Info]
Title: Broadside Captions
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,{font_size},{white},{highlight_color},{outline_color},&H80000000&,-1,0,0,0,100,100,0,0,1,2,1,2,20,20,{y_margin},1
Style: Highlight,Arial,{font_size},{highlight_color},{highlight_color},{outline_color},&H80000000&,-1,0,0,0,100,100,0,0,1,2,1,2,20,20,{y_margin},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def _format_ass_time(seconds: float) -> str:
    """Format seconds as ASS timestamp H:MM:SS.cc."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def _align_words_to_audio(
    audio_path: Path,
    text: str,
) -> list[dict]:
    """Use faster-whisper to align text against audio and get word timestamps.

    Args:
        audio_path: Path to audio file (extracted from scene MP4).
        text: The known script text to align against.

    Returns:
        List of dicts with 'word', 'start', 'end' keys.
    """
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        raise CaptionError(
            "faster-whisper is required for caption generation. "
            "Install it with: pip install faster-whisper"
        )

    model = WhisperModel("base", device="cpu", compute_type="int8")

    # Transcribe with word timestamps to get alignment
    segments, _info = model.transcribe(
        str(audio_path),
        word_timestamps=True,
        initial_prompt=text,
    )

    words = []
    for segment in segments:
        if segment.words:
            for w in segment.words:
                words.append({
                    "word": w.word.strip(),
                    "start": w.start,
                    "end": w.end,
                })

    if not words:
        # Fallback: evenly distribute words across audio duration
        logger.warning("Whisper alignment returned no words, using even distribution")
        ffprobe = shutil.which("ffprobe")
        if ffprobe:
            result = subprocess.run(
                [
                    ffprobe, "-v", "error",
                    "-show_entries", "format=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1",
                    str(audio_path),
                ],
                capture_output=True,
                text=True,
            )
            duration = float(result.stdout.strip()) if result.returncode == 0 else 5.0
        else:
            duration = 5.0

        text_words = text.split()
        if text_words:
            per_word = duration / len(text_words)
            for i, tw in enumerate(text_words):
                words.append({
                    "word": tw,
                    "start": i * per_word,
                    "end": (i + 1) * per_word,
                })

    return words


def _extract_audio(scene_mp4: Path, output_wav: Path) -> None:
    """Extract audio from an MP4 to WAV for whisper processing."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise CaptionError("ffmpeg not found on PATH")

    result = subprocess.run(
        [
            ffmpeg, "-y",
            "-i", str(scene_mp4),
            "-vn", "-acodec", "pcm_s16le",
            "-ar", "16000", "-ac", "1",
            str(output_wav),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        raise CaptionError(f"Audio extraction failed: {result.stderr}")


def generate_captions(
    episode: Episode,
    scene_files: dict[str, Path],
    show_config: ShowConfig,
) -> Path:
    """Generate word-by-word karaoke captions as an ASS subtitle file.

    Processes each talk scene's audio with faster-whisper alignment,
    then generates ASS events where the current word is highlighted.
    Card scenes and end cards are skipped.

    Args:
        episode: Episode schema with scenes and text.
        scene_files: Mapping of scene_id to rendered MP4 path.
        show_config: Show configuration for styling.

    Returns:
        Path to the generated .ass subtitle file.
    """
    ass_content = _generate_ass_header(show_config)

    # Calculate cumulative timeline offset for each scene
    timeline_offset = 0.0

    for scene in episode.scenes:
        if isinstance(scene, CardScene):
            timeline_offset += scene.duration
            continue

        if not isinstance(scene, TalkScene):
            # Silent/Ad scenes: add their duration and skip
            duration = getattr(scene, "duration", 0.0)
            timeline_offset += duration
            continue

        scene_file = scene_files.get(scene.id)
        if not scene_file or not scene_file.exists():
            logger.warning("Scene file not found for %s, skipping captions", scene.id)
            continue

        # Extract audio for alignment
        wav_path = scene_file.parent / f"{scene.id}_caption_audio.wav"
        _extract_audio(scene_file, wav_path)

        # Align words
        words = _align_words_to_audio(wav_path, scene.text)

        # Clean up temp wav
        wav_path.unlink(missing_ok=True)

        if not words:
            continue

        # Get scene duration for timeline offset calculation
        scene_duration = words[-1]["end"] if words else 0.0

        # Generate ASS events: for each word's time window, show all words
        # with the current one highlighted
        all_word_texts = [w["word"] for w in words]

        for i, word_info in enumerate(words):
            abs_start = timeline_offset + word_info["start"]
            abs_end = timeline_offset + word_info["end"]
            start_ts = _format_ass_time(abs_start)
            end_ts = _format_ass_time(abs_end)

            # Build line with current word highlighted using override tags
            parts = []
            for j, wt in enumerate(all_word_texts):
                if j == i:
                    parts.append(f"{{\\rHighlight}}{wt}{{\\rDefault}}")
                else:
                    parts.append(wt)
            line_text = " ".join(parts)

            ass_content += (
                f"Dialogue: 0,{start_ts},{end_ts},Default,,0,0,0,,{line_text}\n"
            )

        # Advance timeline by scene duration plus any pause
        timeline_offset += scene_duration + scene.pause_after

    # Write ASS file
    output_dir = list(scene_files.values())[0].parent if scene_files else Path("build")
    ass_path = output_dir / f"{episode.episode}-captions.ass"
    ass_path.write_text(ass_content, encoding="utf-8")
    logger.info("Generated captions: %s", ass_path)
    return ass_path


def burn_captions(video_path: Path, ass_path: Path, output_path: Path) -> Path:
    """Burn ASS subtitles into a video file.

    Args:
        video_path: Input video to subtitle.
        ass_path: Path to ASS subtitle file.
        output_path: Path for the output video with burned-in captions.

    Returns:
        Path to the output video.
    """
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise CaptionError("ffmpeg not found on PATH")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Use the ass filter to burn subtitles
    # Escape colons and backslashes in path for ffmpeg filter syntax
    ass_path_escaped = str(ass_path).replace("\\", "\\\\").replace(":", "\\:")

    result = subprocess.run(
        [
            ffmpeg, "-y",
            "-i", str(video_path),
            "-vf", f"ass={ass_path_escaped}",
            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", "18",
            "-pix_fmt", "yuv420p",
            "-c:a", "copy",
            "-movflags", "+faststart",
            str(output_path),
        ],
        capture_output=True,
        text=True,
        timeout=600,
    )
    if result.returncode != 0:
        raise CaptionError(f"Subtitle burn failed: {result.stderr}")

    logger.info("Burned captions into: %s", output_path)
    return output_path
