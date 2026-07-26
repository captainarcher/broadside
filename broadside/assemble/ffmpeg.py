"""FFmpeg-based deterministic video assembly pipeline.

Concatenates rendered scene MP4s with filters for pauses, cards,
silent scenes, zooms, and ads. Normalizes audio and outputs H.264
1080p with fast-start.

Strategy: process each scene into a normalized intermediate clip,
then use concat demuxer to join them. This avoids complex filter
graphs and is more reliable across ffmpeg versions.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

from ..config import ShowConfig
from ..schema import (
    AdScene,
    CardScene,
    DemoScene,
    DiagramScene,
    Episode,
    SilentScene,
    TalkScene,
)

logger = logging.getLogger(__name__)


class FFmpegError(Exception):
    """Raised when an ffmpeg command fails."""


def _check_ffmpeg() -> str:
    path = shutil.which("ffmpeg")
    if not path:
        raise FFmpegError("ffmpeg not found. Install with: brew install ffmpeg")
    return path


def _run_ffmpeg(args: list[str], desc: str = "ffmpeg") -> subprocess.CompletedProcess:
    logger.debug("Running: %s", " ".join(args))
    result = subprocess.run(
        args,
        capture_output=True,
        text=True,
        timeout=600,
    )
    if result.returncode != 0:
        raise FFmpegError(f"{desc} failed (exit {result.returncode}):\n{result.stderr[-1000:]}")
    return result


def _find_scene_file(episode_id: str, scene_id: str, build_dir: Path) -> Path | None:
    """Find a rendered scene file by globbing for the content-hashed filename."""
    scenes_dir = build_dir / episode_id / "scenes"
    if not scenes_dir.exists():
        return None
    matches = sorted(scenes_dir.glob(f"{scene_id}-*.mp4"))
    if matches:
        return matches[0]
    # Fallback: exact name without hash
    exact = scenes_dir / f"{scene_id}.mp4"
    return exact if exact.exists() else None


def _prepare_talk_scene(
    scene: TalkScene,
    scene_file: Path,
    show_config: ShowConfig,
    output: Path,
    illustration: Path | None = None,
) -> None:
    """Normalize a talk scene clip: scale, optional zoom, optional pause, optional PiP illustration.

    If *illustration* is provided, overlays it as a picture-in-picture graphic
    in the upper-right corner (news-style backdrop), sliding in after 1s and
    fading out 1s before the scene ends.
    """
    ffmpeg = _check_ffmpeg()
    w, h = show_config.dimensions

    if illustration and illustration.exists():
        # PiP overlay approach: two inputs, filter_complex
        # For 9:16 vertical: illustration fills ~40% width, upper-right area
        # For 16:9 horizontal: illustration fills ~30% width, upper-right
        is_vertical = h > w
        pip_w = int(w * 0.40) if is_vertical else int(w * 0.30)
        pip_x = int(w * 0.55) if is_vertical else int(w * 0.65)
        pip_y = int(h * 0.05) if is_vertical else int(h * 0.08)
        fade_in_start = 0.8    # appear after 0.8s
        fade_in_dur = 0.5
        # PiP stays visible for 4 seconds then fades out
        fade_out_start = fade_in_start + 4.0
        fade_out_dur = 0.5

        # Build the main video filter
        main_vf = f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2"
        if scene.zoom:
            main_vf = f"crop=iw/1.12:ih/1.12," + main_vf
        if scene.pause_after > 0:
            main_vf += f",tpad=stop_mode=clone:stop_duration={scene.pause_after}"

        # Build overlay filter: scale illustration, position upper-right
        # Simple overlay — visible throughout the scene
        filter_complex = (
            f"[0:v]{main_vf}[main];"
            f"[1:v]scale={pip_w}:-1[pip];"
            f"[main][pip]overlay=x={pip_x}:y={pip_y}[vout]"
        )

        af_parts = []
        if scene.pause_after > 0:
            af_parts.append(f"apad=pad_dur={scene.pause_after}")

        args = [ffmpeg, "-y", "-i", str(scene_file), "-loop", "1", "-i", str(illustration)]
        args.extend(["-filter_complex", filter_complex])
        args.extend(["-map", "[vout]", "-map", "0:a"])
        if af_parts:
            args.extend(["-af", ",".join(af_parts)])
        args.extend([
            "-c:v", "libx264", "-preset", "fast", "-crf", "18",
            "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2",
            "-pix_fmt", "yuv420p", "-r", "30",
            "-shortest",
            str(output),
        ])
    else:
        # No illustration — simple pipeline
        vf_parts = [f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2"]
        if scene.zoom:
            vf_parts.insert(0, "crop=iw/1.12:ih/1.12")
        if scene.pause_after > 0:
            vf_parts.append(f"tpad=stop_mode=clone:stop_duration={scene.pause_after}")
        vf = ",".join(vf_parts)

        af_parts = []
        if scene.pause_after > 0:
            af_parts.append(f"apad=pad_dur={scene.pause_after}")

        args = [ffmpeg, "-y", "-i", str(scene_file)]
        args.extend(["-vf", vf])
        if af_parts:
            args.extend(["-af", ",".join(af_parts)])
        args.extend([
            "-c:v", "libx264", "-preset", "fast", "-crf", "18",
            "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2",
            "-pix_fmt", "yuv420p", "-r", "30",
            str(output),
        ])
    _run_ffmpeg(args, desc=f"prepare talk {scene.id}")


def _prepare_card_scene(
    scene: CardScene,
    show_config: ShowConfig,
    output: Path,
) -> None:
    """Create a still-image video clip with fade in/out and silent audio."""
    ffmpeg = _check_ffmpeg()
    w, h = show_config.dimensions
    duration = scene.duration
    fade_out_start = max(0, duration - 0.1)

    args = [
        ffmpeg, "-y",
        "-loop", "1", "-t", str(duration), "-i", str(scene.asset),
        "-f", "lavfi", "-t", str(duration), "-i", "anullsrc=r=48000:cl=stereo",
        "-vf", (
            f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
            f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,"
            f"fade=t=in:st=0:d=0.1,fade=t=out:st={fade_out_start}:d=0.1"
        ),
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        "-c:a", "aac", "-b:a", "128k",
        "-pix_fmt", "yuv420p", "-r", "30",
        "-shortest",
        str(output),
    ]
    _run_ffmpeg(args, desc=f"prepare card {scene.id}")


def _prepare_silent_scene(
    scene: SilentScene,
    show_config: ShowConfig,
    build_dir: Path,
    output: Path,
) -> None:
    """Create a silent scene: solid color background with optional overlay."""
    ffmpeg = _check_ffmpeg()
    w, h = show_config.dimensions
    duration = scene.duration
    bg_color = show_config.background_color.lstrip("#")

    if scene.overlay:
        overlay_path = Path(scene.overlay)
        if not overlay_path.is_absolute():
            overlay_path = build_dir / scene.overlay
        args = [
            ffmpeg, "-y",
            "-f", "lavfi", "-t", str(duration),
            "-i", f"color=c={bg_color}:s={w}x{h}:r=30",
            "-loop", "1", "-t", str(duration), "-i", str(overlay_path),
            "-f", "lavfi", "-t", str(duration), "-i", "anullsrc=r=48000:cl=stereo",
            "-filter_complex", f"[0:v][1:v]overlay=(W-w)/2:(H-h)/2[vout]",
            "-map", "[vout]", "-map", "2:a",
            "-c:v", "libx264", "-preset", "fast", "-crf", "18",
            "-c:a", "aac", "-b:a", "128k",
            "-pix_fmt", "yuv420p",
            "-shortest",
            str(output),
        ]
    else:
        args = [
            ffmpeg, "-y",
            "-f", "lavfi", "-t", str(duration),
            "-i", f"color=c={bg_color}:s={w}x{h}:r=30",
            "-f", "lavfi", "-t", str(duration), "-i", "anullsrc=r=48000:cl=stereo",
            "-c:v", "libx264", "-preset", "fast", "-crf", "18",
            "-c:a", "aac", "-b:a", "128k",
            "-pix_fmt", "yuv420p",
            str(output),
        ]
    _run_ffmpeg(args, desc=f"prepare silent {scene.id}")


def _prepare_ad_scene(
    scene: AdScene,
    ad_file: Path,
    show_config: ShowConfig,
    output: Path,
) -> None:
    """Scale and normalize an ad clip."""
    ffmpeg = _check_ffmpeg()
    w, h = show_config.dimensions
    args = [
        ffmpeg, "-y", "-i", str(ad_file),
        "-vf", f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2",
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2",
        "-pix_fmt", "yuv420p", "-r", "30",
        str(output),
    ]
    _run_ffmpeg(args, desc=f"prepare ad {scene.id}")


def _prepare_demo_scene(
    scene: DemoScene,
    scene_file: Path,
    show_config: ShowConfig,
    output: Path,
) -> None:
    """Composite screen recording with avatar PiP in bottom-left corner.

    The screen recording fills the frame and the HeyGen-rendered avatar
    narration is overlaid as a small picture-in-picture in the bottom-left.
    Audio comes from the avatar narration track.
    """
    ffmpeg = _check_ffmpeg()
    w, h = show_config.dimensions
    pip_w = int(w * 0.25)
    pip_x = int(w * 0.03)
    pip_y = int(h * 0.72)

    recording = Path(scene.recording)

    vf_main = f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2"
    if scene.pause_after > 0:
        vf_main += f",tpad=stop_mode=clone:stop_duration={scene.pause_after}"

    filter_complex = (
        f"[0:v]{vf_main}[recording];"
        f"[1:v]scale={pip_w}:-1[avatar];"
        f"[recording][avatar]overlay=x={pip_x}:y={pip_y}[vout]"
    )

    af_parts = []
    if scene.pause_after > 0:
        af_parts.append(f"apad=pad_dur={scene.pause_after}")

    args = [
        ffmpeg, "-y",
        "-i", str(recording),       # input 0: screen recording (video only used)
        "-i", str(scene_file),       # input 1: avatar narration (video + audio)
        "-filter_complex", filter_complex,
        "-map", "[vout]", "-map", "1:a",  # video from composite, audio from avatar
    ]
    if af_parts:
        args.extend(["-af", ",".join(af_parts)])
    args.extend([
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2",
        "-pix_fmt", "yuv420p", "-r", "30",
        "-shortest",
        str(output),
    ])
    _run_ffmpeg(args, desc=f"prepare demo {scene.id}")


def _get_duration(file: Path) -> float:
    """Get duration of a media file in seconds using ffprobe."""
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise FFmpegError("ffprobe not found. Install with: brew install ffmpeg")
    result = subprocess.run(
        [ffprobe, "-v", "quiet", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(file)],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        raise FFmpegError(f"ffprobe failed on {file}: {result.stderr}")
    return float(result.stdout.strip())


def _prepare_diagram_scene(
    scene: DiagramScene,
    scene_file: Path,
    show_config: ShowConfig,
    output: Path,
) -> None:
    """Show diagram with Ken Burns zoom and avatar PiP in bottom-left.

    The diagram image fills the frame with a slow zoom for visual interest.
    The avatar narration is overlaid as PiP in the bottom-left corner.
    Audio comes from the avatar narration track.
    """
    ffmpeg = _check_ffmpeg()
    w, h = show_config.dimensions
    pip_w = int(w * 0.25)
    pip_x = int(w * 0.03)
    pip_y = int(h * 0.72)

    asset = Path(scene.asset)
    duration = _get_duration(scene_file)
    if scene.pause_after > 0:
        duration += scene.pause_after

    # Ken Burns: slow zoom from 105% to 100% over the narration duration
    frames = int(30 * duration)
    diagram_vf = (
        f"scale={int(w * 1.1)}:{int(h * 1.1)},"
        f"zoompan=z='1.05-0.05*on/{frames}'"
        f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
        f":d={frames}:s={w}x{h}:fps=30"
    )

    filter_complex = (
        f"[0:v]{diagram_vf}[diagram];"
        f"[1:v]scale={pip_w}:-1[avatar];"
        f"[diagram][avatar]overlay=x={pip_x}:y={pip_y}[vout]"
    )

    af_parts = []
    if scene.pause_after > 0:
        af_parts.append(f"apad=pad_dur={scene.pause_after}")

    args = [
        ffmpeg, "-y",
        "-loop", "1", "-i", str(asset),   # input 0: diagram image
        "-i", str(scene_file),              # input 1: avatar narration
        "-filter_complex", filter_complex,
        "-map", "[vout]", "-map", "1:a",
    ]
    if af_parts:
        args.extend(["-af", ",".join(af_parts)])
    args.extend([
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2",
        "-pix_fmt", "yuv420p", "-r", "30",
        "-shortest",
        str(output),
    ])
    _run_ffmpeg(args, desc=f"prepare diagram {scene.id}")


def _find_illustrations(episode_id: str) -> list[Path]:
    """Find courtroom sketch illustrations for an episode.

    Searches assets/illustrations/ for directories matching the episode ID
    or keywords from the episode ID. Returns all image files found, sorted.
    """
    illust_base = Path("assets/illustrations")
    if not illust_base.exists():
        return []

    # Build search terms from episode ID
    # ep-20260725-pope-app -> try full slug first, then multi-word combos
    slug = episode_id.lower()
    # Strip ep- prefix and date
    import re
    slug_clean = re.sub(r"^ep-\d{8}-", "", slug)

    found: list[Path] = []
    for topic_dir in illust_base.iterdir():
        if not topic_dir.is_dir():
            continue
        dir_name = topic_dir.name.lower()

        # Exact match on the cleaned slug (best)
        if dir_name == slug_clean:
            images = sorted(
                list(topic_dir.glob("*.webp"))
                + list(topic_dir.glob("*.png"))
                + list(topic_dir.glob("*.jpg"))
            )
            found.extend(images)
            continue

        # Multi-word match: require ALL non-trivial keywords to match
        parts = [p for p in slug_clean.split("-") if len(p) > 3]
        if parts and all(part in dir_name for part in parts):
            images = sorted(
                list(topic_dir.glob("*.webp"))
                + list(topic_dir.glob("*.png"))
                + list(topic_dir.glob("*.jpg"))
            )
            found.extend(images)

    return found


def _prepare_illustration_clip(
    image_path: Path,
    show_config: ShowConfig,
    output: Path,
    duration: float = 3.0,
) -> None:
    """Create a video clip from an illustration with Ken Burns pan effect."""
    ffmpeg = _check_ffmpeg()
    w, h = show_config.dimensions
    # Ken Burns: slow zoom from 110% to 100% over duration
    args = [
        ffmpeg, "-y",
        "-loop", "1", "-t", str(duration), "-i", str(image_path),
        "-f", "lavfi", "-t", str(duration), "-i", "anullsrc=r=48000:cl=stereo",
        "-vf", (
            f"scale={int(w * 1.15)}:{int(h * 1.15)},"
            f"zoompan=z='1.1-0.1*on/(25*{duration})':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
            f":d={int(25 * duration)}:s={w}x{h}:fps=25,"
            f"fade=t=in:st=0:d=0.3,fade=t=out:st={duration - 0.3}:d=0.3"
        ),
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        "-c:a", "aac", "-b:a", "128k",
        "-pix_fmt", "yuv420p", "-r", "30",
        "-shortest",
        str(output),
    ]
    _run_ffmpeg(args, desc=f"prepare illustration {image_path.name}")


def assemble_timeline(
    episode: Episode,
    show_config: ShowConfig,
    build_dir: Path,
    out_dir: Path,
) -> Path:
    """Assemble episode scenes into a single timeline MP4.

    1. Process each scene into a normalized intermediate clip.
    2. Write a concat demuxer file listing all clips.
    3. Concatenate and normalize audio to -16 LUFS.
    4. Output H.264, 1080p, yuv420p, faststart.
    """
    _check_ffmpeg()
    ffmpeg = _check_ffmpeg()
    out_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="broadside-") as tmpdir:
        tmp = Path(tmpdir)
        clip_paths: list[Path] = []

        # Find illustrations to overlay on talk scenes (PiP news-style)
        illustrations = _find_illustrations(episode.episode)
        illust_idx = 0
        # Distribute illustrations across talk scenes (skip first and last)
        talk_scenes_list = [
            (i, s) for i, s in enumerate(episode.scenes) if isinstance(s, TalkScene)
        ]
        pip_scene_indices: set[int] = set()
        if illustrations and len(talk_scenes_list) > 2:
            # Skip first scene (intro) and last scene (signoff), distribute evenly
            eligible = talk_scenes_list[1:-1]
            step = max(1, len(eligible) // min(len(illustrations), len(eligible)))
            for j in range(0, len(eligible), step):
                if illust_idx < len(illustrations):
                    pip_scene_indices.add(eligible[j][0])
                    illust_idx += 1
        illust_idx = 0  # reset for use in loop
        clip_counter = 0

        for i, scene in enumerate(episode.scenes):
            clip_out = tmp / f"clip_{i:03d}_{scene.id}.mp4"

            if isinstance(scene, TalkScene):
                scene_file = _find_scene_file(episode.episode, scene.id, build_dir)
                if not scene_file or not scene_file.exists():
                    raise FFmpegError(f"Scene file not found for {scene.id}")
                # Overlay illustration as PiP if this scene is eligible
                pip_illust = None
                if i in pip_scene_indices and illust_idx < len(illustrations):
                    pip_illust = illustrations[illust_idx]
                    illust_idx += 1
                    logger.info("PiP overlay on %s: %s", scene.id, pip_illust.name)
                _prepare_talk_scene(scene, scene_file, show_config, clip_out, illustration=pip_illust)

            elif isinstance(scene, CardScene):
                asset_path = Path(scene.asset)
                if not asset_path.exists():
                    logger.warning("Card asset not found: %s — skipping", scene.asset)
                    continue
                _prepare_card_scene(scene, show_config, clip_out)

            elif isinstance(scene, SilentScene):
                _prepare_silent_scene(scene, show_config, build_dir, clip_out)

            elif isinstance(scene, DemoScene):
                scene_file = _find_scene_file(episode.episode, scene.id, build_dir)
                if not scene_file or not scene_file.exists():
                    raise FFmpegError(f"Scene file not found for {scene.id}")
                _prepare_demo_scene(scene, scene_file, show_config, clip_out)

            elif isinstance(scene, DiagramScene):
                scene_file = _find_scene_file(episode.episode, scene.id, build_dir)
                if not scene_file or not scene_file.exists():
                    raise FFmpegError(f"Scene file not found for {scene.id}")
                _prepare_diagram_scene(scene, scene_file, show_config, clip_out)

            elif isinstance(scene, AdScene):
                # Find ad video: try concept path directly, then load concept YAML for name
                ad_file = None
                concept_path = Path(scene.concept)
                if concept_path.exists():
                    # Load the concept to get the product name (used as render dir)
                    import yaml as _yaml
                    with open(concept_path) as _f:
                        concept_data = _yaml.safe_load(_f)
                    ad_name = concept_data.get("name", concept_path.stem)
                    ad_file = Path(f"ads/rendered/{ad_name}/final.mp4")
                if not ad_file or not ad_file.exists():
                    # Fallback: try using concept field directly as dir name
                    ad_file = Path(f"ads/rendered/{scene.concept}/final.mp4")
                if not ad_file.exists():
                    logger.warning("Ad file not found: %s — skipping", ad_file)
                    continue
                _prepare_ad_scene(scene, ad_file, show_config, clip_out)

            else:
                logger.warning("Unknown scene type: %s — skipping", type(scene))
                continue

            clip_paths.append(clip_out)
            clip_counter += 1
            logger.info("Prepared clip %d/%d: %s", i + 1, len(episode.scenes), scene.id)

        if not clip_paths:
            raise FFmpegError("No clips to assemble")

        # Write concat demuxer file
        concat_file = tmp / "concat.txt"
        with open(concat_file, "w") as f:
            for clip in clip_paths:
                f.write(f"file '{clip}'\n")

        # Concatenate all clips
        concat_out = tmp / "concat.mp4"
        args = [
            ffmpeg, "-y",
            "-f", "concat", "-safe", "0", "-i", str(concat_file),
            "-c", "copy",
            str(concat_out),
        ]
        _run_ffmpeg(args, desc="concatenate clips")

        # Normalize audio to -16 LUFS and finalize
        final_out = out_dir / f"assembled-{episode.episode}.mp4"
        args = [
            ffmpeg, "-y", "-i", str(concat_out),
            "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
            "-c:v", "copy",
            "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart",
            str(final_out),
        ]
        _run_ffmpeg(args, desc="normalize audio")

    logger.info("Assembled: %s", final_out)
    return final_out
