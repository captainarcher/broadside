"""Async polling for HeyGen v3 video generation status.

Uses exponential back-off starting at 5 s, doubling up to 60 s,
with a hard wall-clock timeout (default 600 s / 10 min).
"""

from __future__ import annotations

import asyncio
import time

import httpx

HEYGEN_BASE = "https://api.heygen.com"


class RenderTimeout(Exception):
    """Raised when polling exceeds *max_wait* seconds."""


class RenderFailed(Exception):
    """Raised when HeyGen reports a terminal failure."""


async def poll_video_status(
    client: httpx.AsyncClient,
    video_id: str,
    api_key: str,
    *,
    max_wait: float = 600,
) -> dict:
    """Poll ``GET /v3/videos/{video_id}`` until the video completes.

    Parameters
    ----------
    client:
        Shared ``httpx.AsyncClient``.
    video_id:
        HeyGen video ID returned by the create endpoint.
    api_key:
        HeyGen API key (sent as ``X-Api-Key`` header).
    max_wait:
        Maximum wall-clock seconds to wait before raising
        :class:`RenderTimeout`.

    Returns
    -------
    dict
        The full video data dict on successful completion.

    Raises
    ------
    RenderTimeout
        If *max_wait* is exceeded.
    RenderFailed
        If HeyGen returns a terminal error status.
    """
    url = f"{HEYGEN_BASE}/v3/videos/{video_id}"
    headers = {"X-Api-Key": api_key}

    interval = 5.0
    max_interval = 60.0
    deadline = time.monotonic() + max_wait

    while True:
        resp = await client.get(url, headers=headers)
        resp.raise_for_status()
        data = resp.json().get("data", resp.json())

        status = data.get("status", "")

        if status == "completed":
            return data

        if status in ("failed", "error"):
            error_msg = data.get("error", data.get("message", "Unknown error"))
            raise RenderFailed(
                f"Video {video_id} failed: {error_msg}"
            )

        if time.monotonic() >= deadline:
            raise RenderTimeout(
                f"Video {video_id} did not complete within {max_wait}s "
                f"(last status: {status})"
            )

        await asyncio.sleep(interval)
        interval = min(interval * 2, max_interval)
