"""Shared Playwright browser setup with stealth-like configuration."""

from __future__ import annotations

import asyncio
import random
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from playwright.async_api import Browser, BrowserContext, async_playwright


# Realistic browser fingerprint settings
_DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/127.0.0.0 Safari/537.36"
)
_DEFAULT_VIEWPORT = {"width": 1280, "height": 900}
_DEFAULT_LOCALE = "en-US"
_DEFAULT_TIMEZONE = "America/New_York"


async def create_browser(
    headed: bool = True,
) -> tuple[Browser, BrowserContext]:
    """Launch Chromium with stealth-like settings and return (browser, context).

    Caller is responsible for closing browser when done.
    Use ``managed_browser`` context manager for automatic cleanup.
    """
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(
        headless=not headed,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--no-first-run",
            "--no-default-browser-check",
        ],
    )
    context = await browser.new_context(
        user_agent=_DEFAULT_USER_AGENT,
        viewport=_DEFAULT_VIEWPORT,
        locale=_DEFAULT_LOCALE,
        timezone_id=_DEFAULT_TIMEZONE,
        # Reduce automation detection signals
        java_script_enabled=True,
        bypass_csp=False,
        ignore_https_errors=False,
    )

    # Override navigator.webdriver to false
    await context.add_init_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => false})"
    )

    return browser, context


@asynccontextmanager
async def managed_browser(
    headed: bool = True,
) -> AsyncGenerator[tuple[Browser, BrowserContext], None]:
    """Context manager that creates and cleans up a browser + context."""
    browser, context = await create_browser(headed=headed)
    try:
        yield browser, context
    finally:
        await context.close()
        await browser.close()


async def human_delay(min_sec: float = 1.0, max_sec: float = 3.0) -> None:
    """Sleep for a random duration to mimic human interaction timing."""
    await asyncio.sleep(random.uniform(min_sec, max_sec))


async def human_type(page, selector: str, text: str) -> None:
    """Type text into an element with randomized per-keystroke delays."""
    element = page.locator(selector)
    await element.click()
    for char in text:
        await element.press(char)
        await asyncio.sleep(random.uniform(0.03, 0.12))
