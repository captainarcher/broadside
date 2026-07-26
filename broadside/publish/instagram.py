"""Instagram publishing via Playwright browser automation."""

from __future__ import annotations

import asyncio
from pathlib import Path

from ..config import BroadsideConfig
from .browser import create_browser, human_delay
from .cookies import inject_cookies


async def _publish_instagram(
    config: BroadsideConfig,
    episode_id: str,
    video_path: Path,
    metadata: dict,
) -> str:
    """Async implementation of Instagram publishing."""
    if not video_path.exists():
        raise FileNotFoundError(f"Video not found: {video_path}")

    ig_config = config.publishing.instagram
    headed = ig_config.browser == "headed"

    browser, context = await create_browser(headed=headed)
    try:
        await inject_cookies(context, "instagram")
        page = await context.new_page()

        # Navigate to Instagram
        print("Navigating to Instagram...")
        await page.goto("https://www.instagram.com/", wait_until="networkidle")
        await human_delay(2.0, 4.0)

        # Click the create/new post button (the + icon in nav)
        print("Opening create post dialog...")
        create_btn = page.locator('[aria-label="New post"]').first
        if not await create_btn.is_visible():
            # Fallback selectors for different IG UI versions
            create_btn = page.locator('svg[aria-label="New post"]').first
        if not await create_btn.is_visible():
            create_btn = page.locator('[data-testid="new-post-button"]').first
        if not await create_btn.is_visible():
            # Try the nav bar create button with generic selector
            create_btn = page.locator('a[href="/create/"]').first
        await create_btn.click()
        await human_delay()

        # Handle the file chooser for video selection
        print(f"Selecting video: {video_path.name}")
        async with page.expect_file_chooser() as fc_info:
            # Click "Select from computer" button in the upload dialog
            select_btn = page.get_by_text("Select from computer", exact=False).first
            if not await select_btn.is_visible():
                select_btn = page.get_by_text("Select From Computer", exact=False).first
            await select_btn.click()
        file_chooser = await fc_info.value
        await file_chooser.set_files(str(video_path))
        await human_delay(2.0, 4.0)

        # Wait for video processing
        print("Waiting for video processing...")
        # Instagram shows a loading indicator while processing
        await page.wait_for_timeout(5000)
        await human_delay(2.0, 5.0)

        # Click through to the caption/share screen
        # Click "Next" button (may appear multiple times for crop/filter/etc.)
        for step in ("crop", "filter"):
            next_btn = page.get_by_role("button", name="Next").first
            if await next_btn.is_visible():
                await next_btn.click()
                await human_delay()

        # Enter caption
        caption = metadata.get("caption", "")
        hashtags = metadata.get("hashtags", [])
        full_caption = caption
        if hashtags:
            tag_str = " ".join(f"#{t}" for t in hashtags)
            full_caption = f"{caption}\n\n{tag_str}" if caption else tag_str

        print("Entering caption...")
        caption_area = page.locator('[aria-label="Write a caption..."]').first
        if not await caption_area.is_visible():
            caption_area = page.locator('[contenteditable="true"]').first
        await caption_area.click()
        await caption_area.fill(full_caption)
        await human_delay()

        # Click Share/Publish
        print("Publishing post...")
        share_btn = page.get_by_role("button", name="Share").first
        if not await share_btn.is_visible():
            share_btn = page.get_by_text("Share", exact=True).first
        await share_btn.click()

        # Wait for upload to complete — look for "Your reel has been shared"
        # or similar confirmation text
        print("Waiting for upload confirmation...")
        for _ in range(30):
            await page.wait_for_timeout(2000)
            # Check for success indicators
            page_text = await page.inner_text("body")
            if any(phrase in page_text.lower() for phrase in [
                "reel has been shared",
                "post has been shared",
                "your post has been",
                "shared",
            ]):
                break
            # Check if URL changed to a post URL
            if "/p/" in page.url or "/reel/" in page.url:
                break

        await human_delay(2.0, 4.0)

        # Extract the post URL
        post_url = page.url
        if "/p/" in post_url or "/reel/" in post_url:
            print(f"Instagram post published: {post_url}")
            return post_url

        # Navigate to profile to find the latest post
        print("Finding posted content on profile...")
        await page.goto("https://www.instagram.com/", wait_until="networkidle")
        await human_delay(1.0, 2.0)
        # Click profile icon
        profile_link = page.locator('a[href*="/' + '"]').filter(has=page.locator('img[alt*="profile"]'))
        if await profile_link.count() == 0:
            # Fallback: use direct profile URL from cookies
            await page.goto("https://www.instagram.com/accounts/edit/", wait_until="networkidle")
            post_url = "https://www.instagram.com/ (posted — check profile for URL)"
        else:
            post_url = "https://www.instagram.com/ (posted — check profile for URL)"

        print(f"Instagram post published: {post_url}")
        return post_url

    finally:
        await context.close()
        await browser.close()


def publish_to_instagram(
    config: BroadsideConfig,
    episode_id: str,
    video_path: Path,
    metadata: dict,
) -> str:
    """Upload a video to Instagram via browser automation.

    Parameters
    ----------
    config : BroadsideConfig
        Project configuration.
    episode_id : str
        Episode identifier for logging.
    video_path : Path
        Path to the video file to upload.
    metadata : dict
        Keys: caption (str), hashtags (list[str]).

    Returns
    -------
    str
        URL of the published Instagram post.
    """
    return asyncio.run(
        _publish_instagram(config, episode_id, video_path, metadata)
    )
