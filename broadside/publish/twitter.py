"""X/Twitter publishing via Playwright browser automation.

Uses cookie-based auth to post tweets with video attachments,
avoiding Twitter's $200/mo API paywall for media uploads.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from ..config import BroadsideConfig
from .browser import create_browser, human_delay, human_type
from .cookies import inject_cookies


async def _publish_twitter(
    config: BroadsideConfig,
    episode_id: str,
    video_path: Path,
    metadata: dict,
) -> str:
    """Async implementation of X/Twitter publishing via browser."""
    if not video_path.exists():
        raise FileNotFoundError(f"Video not found: {video_path}")

    browser, context = await create_browser(headed=True)
    try:
        await inject_cookies(context, "twitter")
        page = await context.new_page()

        # Navigate to X/Twitter compose
        print("Navigating to X...")
        await page.goto("https://x.com/compose/post", wait_until="networkidle")
        await human_delay(2.0, 4.0)

        # If redirected to login, the cookies may have expired
        if "login" in page.url.lower():
            raise RuntimeError(
                "Twitter cookies expired. Re-export and run: broadside auth setup twitter"
            )

        # Enter tweet text
        caption = metadata.get("caption", "")
        hashtags = metadata.get("hashtags", [])
        full_text = caption
        if hashtags:
            tag_str = " ".join(f"#{t}" for t in hashtags)
            full_text = f"{caption}\n\n{tag_str}" if caption else tag_str
        # Truncate to 280 chars
        full_text = full_text[:280]

        print("Entering tweet text...")
        text_area = page.locator('[data-testid="tweetTextarea_0"]').first
        if not await text_area.is_visible():
            text_area = page.locator('[contenteditable="true"]').first
        await text_area.click()
        await human_type(page, full_text)
        await human_delay()

        # Attach video via file input
        print(f"Attaching video: {video_path.name}")
        file_input = page.locator('input[data-testid="fileInput"]').first
        if not await file_input.count():
            file_input = page.locator('input[type="file"][accept*="video"]').first
        if not await file_input.count():
            file_input = page.locator('input[type="file"]').first
        await file_input.set_input_files(str(video_path))

        # Wait for video to process
        print("Waiting for video processing...")
        await page.wait_for_timeout(5000)
        # Poll until the post button is enabled (video finished processing)
        for _ in range(60):
            post_btn = page.locator('[data-testid="tweetButton"]').first
            if await post_btn.is_enabled():
                break
            await page.wait_for_timeout(3000)
            print("  Still processing...")

        await human_delay(1.0, 2.0)

        # Click Post
        print("Posting tweet...")
        post_btn = page.locator('[data-testid="tweetButton"]').first
        await post_btn.click()

        # Wait for post confirmation
        await human_delay(3.0, 6.0)
        await page.wait_for_timeout(5000)

        # Try to find the posted tweet URL
        post_url = page.url
        # X typically redirects or shows the tweet after posting
        if "/compose" in post_url or "/home" in post_url:
            # Navigate to profile to find latest tweet
            print("Finding posted tweet URL...")
            await page.goto("https://x.com/home", wait_until="networkidle")
            await human_delay(2.0, 3.0)
            # Look for the most recent tweet link
            tweet_links = page.locator('a[href*="/status/"]')
            count = await tweet_links.count()
            if count > 0:
                href = await tweet_links.first.get_attribute("href")
                if href:
                    post_url = f"https://x.com{href}" if href.startswith("/") else href

        print(f"Tweet published: {post_url}")
        return post_url

    finally:
        await context.close()
        await browser.close()


def publish_to_twitter(
    config: BroadsideConfig,
    episode_id: str,
    video_path: Path,
    metadata: dict,
) -> str:
    """Upload a video to X/Twitter via browser automation.

    Uses cookie-based authentication to bypass Twitter's paid API
    requirement for media uploads.
    """
    return asyncio.run(
        _publish_twitter(config, episode_id, video_path, metadata)
    )
