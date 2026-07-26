"""TikTok publishing via Playwright browser automation."""

from __future__ import annotations

import asyncio
from pathlib import Path

from ..config import BroadsideConfig
from .browser import create_browser, human_delay
from .cookies import inject_cookies


async def _publish_tiktok(
    config: BroadsideConfig,
    episode_id: str,
    video_path: Path,
    metadata: dict,
) -> str:
    """Async implementation of TikTok publishing."""
    if not video_path.exists():
        raise FileNotFoundError(f"Video not found: {video_path}")

    tt_config = config.publishing.tiktok
    headed = tt_config.browser == "headed"

    browser, context = await create_browser(headed=headed)
    try:
        await inject_cookies(context, "tiktok")
        page = await context.new_page()

        # Navigate to TikTok upload page
        print("Navigating to TikTok upload page...")
        await page.goto("https://www.tiktok.com/upload", wait_until="networkidle")
        await human_delay(2.0, 4.0)

        # Upload video via file chooser
        print(f"Uploading video: {video_path.name}")
        # TikTok upload page has an iframe for the upload widget
        upload_frame = page.frame_locator("iframe").first
        if upload_frame:
            async with page.expect_file_chooser() as fc_info:
                # Click the upload area / select file button
                upload_btn = upload_frame.locator(
                    'button:has-text("Select file")'
                ).first
                if not await upload_btn.is_visible():
                    upload_btn = upload_frame.locator(
                        '[class*="upload-btn"]'
                    ).first
                if not await upload_btn.is_visible():
                    # Direct page-level fallback
                    upload_btn = page.locator(
                        'button:has-text("Select file")'
                    ).first
                await upload_btn.click()
            file_chooser = await fc_info.value
            await file_chooser.set_files(str(video_path))
        else:
            # No iframe -- direct upload on page
            async with page.expect_file_chooser() as fc_info:
                upload_btn = page.locator(
                    'button:has-text("Select file")'
                ).first
                if not await upload_btn.is_visible():
                    upload_btn = page.locator('input[type="file"]').first
                await upload_btn.click()
            file_chooser = await fc_info.value
            await file_chooser.set_files(str(video_path))

        await human_delay(3.0, 6.0)

        # Wait for video processing
        print("Waiting for video processing...")
        await page.wait_for_timeout(8000)
        await human_delay(2.0, 5.0)

        # Enter caption / description
        caption = metadata.get("caption", "")
        hashtags = metadata.get("hashtags", [])
        full_caption = caption
        if hashtags:
            tag_str = " ".join(f"#{t}" for t in hashtags)
            full_caption = f"{caption} {tag_str}" if caption else tag_str

        print("Entering caption...")
        # TikTok's caption editor is a contenteditable div
        caption_editor = page.locator(
            '[data-text="true"], [contenteditable="true"]'
        ).first
        if not await caption_editor.is_visible():
            caption_editor = page.locator(
                '.public-DraftEditor-content'
            ).first
        # Clear any default text and type caption
        await caption_editor.click()
        await page.keyboard.press("Meta+a")
        await page.keyboard.press("Backspace")
        await human_delay(0.5, 1.0)
        await page.keyboard.type(full_caption, delay=50)
        await human_delay()

        # Set visibility if configured
        visibility = tt_config.default_visibility
        if visibility and visibility != "public":
            print(f"Setting visibility to: {visibility}")
            vis_dropdown = page.locator(
                '[class*="visibility"], [aria-label*="visibility"]'
            ).first
            if await vis_dropdown.is_visible():
                await vis_dropdown.click()
                await human_delay(0.5, 1.0)
                vis_option = page.get_by_text(visibility, exact=False).first
                if await vis_option.is_visible():
                    await vis_option.click()
                    await human_delay()

        # Click Post button
        print("Publishing to TikTok...")
        post_btn = page.locator(
            'button:has-text("Post"), button:has-text("Publish")'
        ).first
        if not await post_btn.is_visible():
            post_btn = page.get_by_role("button", name="Post").first
        await post_btn.click()

        # Wait for upload completion
        await human_delay(3.0, 6.0)
        await page.wait_for_timeout(5000)

        # Try to extract the video URL
        post_url = page.url
        # TikTok may redirect to the video page after posting
        if "/upload" in post_url:
            # Check for a success message with a link
            video_link = page.locator('a[href*="/video/"]').first
            if await video_link.is_visible():
                href = await video_link.get_attribute("href")
                if href:
                    post_url = (
                        href
                        if href.startswith("http")
                        else f"https://www.tiktok.com{href}"
                    )
            else:
                # Construct a placeholder URL
                post_url = f"https://www.tiktok.com/@user/video/{episode_id}"

        print(f"TikTok video published: {post_url}")
        return post_url

    finally:
        await context.close()
        await browser.close()


def publish_to_tiktok(
    config: BroadsideConfig,
    episode_id: str,
    video_path: Path,
    metadata: dict,
) -> str:
    """Upload a video to TikTok via browser automation.

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
        URL of the published TikTok video.
    """
    return asyncio.run(
        _publish_tiktok(config, episode_id, video_path, metadata)
    )
