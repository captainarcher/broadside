"""YouTube publishing via YouTube Data API v3 with OAuth 2.0."""

from __future__ import annotations

import json
import os
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from ..config import BroadsideConfig

_SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",  # needed for thumbnail set
]
_TOKENS_DIR = Path.home() / ".broadside" / "tokens"
_TOKEN_PATH = _TOKENS_DIR / "youtube.json"


def _get_client_config() -> dict:
    """Build OAuth client config from environment variables."""
    client_id = os.environ.get("GOOGLE_CLIENT_ID")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise EnvironmentError(
            "GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET must be set. "
            "Create OAuth credentials at https://console.cloud.google.com/apis/credentials"
        )
    return {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }


def _get_credentials() -> Credentials:
    """Load saved credentials or run OAuth browser flow."""
    creds: Credentials | None = None

    if _TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(_TOKEN_PATH), _SCOPES)

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        _save_credentials(creds)
        return creds

    # No valid credentials -- run browser-based OAuth flow
    client_config = _get_client_config()
    flow = InstalledAppFlow.from_client_config(client_config, _SCOPES)
    creds = flow.run_local_server(port=0, open_browser=True)
    _save_credentials(creds)
    return creds


def _save_credentials(creds: Credentials) -> None:
    """Persist credentials to disk."""
    _TOKENS_DIR.mkdir(parents=True, exist_ok=True)
    with open(_TOKEN_PATH, "w") as f:
        f.write(creds.to_json())


def publish_to_youtube(
    config: BroadsideConfig,
    episode_id: str,
    video_path: Path,
    metadata: dict,
) -> str:
    """Upload a video to YouTube and return the video URL.

    Parameters
    ----------
    config : BroadsideConfig
        Project configuration (used for publishing settings).
    episode_id : str
        Episode identifier for logging.
    video_path : Path
        Path to the video file to upload.
    metadata : dict
        Keys: title, description, tags (list[str]), caption_hook.
    """
    if not video_path.exists():
        raise FileNotFoundError(f"Video not found: {video_path}")

    yt_config = config.publishing.youtube
    creds = _get_credentials()
    youtube = build("youtube", "v3", credentials=creds)

    title = metadata.get("title", episode_id)
    description = metadata.get("description", "")
    tags = metadata.get("tags", [])

    body = {
        "snippet": {
            "title": title[:100],  # YouTube title limit
            "description": description[:5000],
            "tags": tags[:500],
            "categoryId": yt_config.category_id,
        },
        "status": {
            "privacyStatus": yt_config.privacy,
            "madeForKids": yt_config.made_for_kids,
            "selfDeclaredMadeForKids": yt_config.made_for_kids,
        },
    }

    # Add synthetic media disclosure if configured
    if yt_config.contains_synthetic_media:
        body["status"]["containsSyntheticMedia"] = True

    media = MediaFileUpload(
        str(video_path),
        mimetype="video/mp4",
        resumable=True,
        chunksize=10 * 1024 * 1024,  # 10 MB chunks
    )

    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media,
    )

    print(f"Uploading {video_path.name} to YouTube...")
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            pct = int(status.progress() * 100)
            print(f"  Upload progress: {pct}%")

    video_id = response["id"]
    video_url = f"https://youtu.be/{video_id}"
    print(f"Upload complete: {video_url}")

    # Upload thumbnail if available (must be under 2MB for YouTube)
    thumbnail = _find_thumbnail(video_path.parent, episode_id)
    if thumbnail:
        try:
            thumb_to_upload = thumbnail
            # Resize if over 2MB
            if thumbnail.stat().st_size > 2 * 1024 * 1024:
                import subprocess
                resized = thumbnail.parent / f"thumb-resized-{thumbnail.name}"
                subprocess.run(
                    ["ffmpeg", "-y", "-i", str(thumbnail),
                     "-vf", "scale='min(1280,iw)':'min(720,ih)':force_original_aspect_ratio=decrease",
                     "-q:v", "2", str(resized.with_suffix(".jpg"))],
                    capture_output=True, timeout=30,
                )
                resized_jpg = resized.with_suffix(".jpg")
                if resized_jpg.exists() and resized_jpg.stat().st_size < 2 * 1024 * 1024:
                    thumb_to_upload = resized_jpg
            mimetype = "image/jpeg" if thumb_to_upload.suffix == ".jpg" else "image/png"
            print(f"Setting thumbnail: {thumb_to_upload.name}")
            youtube.thumbnails().set(
                videoId=video_id,
                media_body=MediaFileUpload(str(thumb_to_upload), mimetype=mimetype),
            ).execute()
            print("Thumbnail set.")
        except Exception as e:
            print(f"Thumbnail upload failed (may need verified channel): {e}")

    return video_url


def _find_thumbnail(episode_dir: Path, episode_id: str) -> Path | None:
    """Find a thumbnail image for the episode.

    Looks for (in order):
    1. thumbnail.png in the episode output directory
    2. contact-sheet-*.png in the episode output directory
    3. First illustration in assets/illustrations/<episode_id>/
    """
    # Custom thumbnail
    thumb = episode_dir / "thumbnail.png"
    if thumb.exists():
        return thumb

    # Contact sheet as fallback
    sheets = list(episode_dir.glob("contact-sheet-*.png"))
    if sheets:
        return sheets[0]

    # Illustration
    illust_dir = Path("assets/illustrations") / episode_id
    if illust_dir.exists():
        pngs = list(illust_dir.glob("*.png"))
        if pngs:
            return pngs[0]

    return None
