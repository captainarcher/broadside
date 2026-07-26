"""Cookie management for browser-automated platforms (Instagram, TikTok)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from playwright.async_api import BrowserContext

_COOKIES_DIR = Path.home() / ".broadside" / "cookies"

# Platform-specific cookie domains used for filtering
_PLATFORM_DOMAINS: dict[str, list[str]] = {
    "instagram": [".instagram.com", "www.instagram.com", "instagram.com"],
    "tiktok": [".tiktok.com", "www.tiktok.com", "tiktok.com"],
    "twitter": [".x.com", "x.com", ".twitter.com", "twitter.com"],
    "x": [".x.com", "x.com", ".twitter.com", "twitter.com"],
}

# Human-readable export instructions per platform
_EXPORT_INSTRUCTIONS: dict[str, str] = {
    "instagram": (
        "Instagram cookie export instructions:\n"
        "  1. Install a browser extension like 'Get cookies.txt LOCALLY'\n"
        "  2. Log in to instagram.com in your browser\n"
        "  3. Navigate to instagram.com and export cookies\n"
        "  4. Save the exported file or copy the contents\n"
    ),
    "tiktok": (
        "TikTok cookie export instructions:\n"
        "  1. Install a browser extension like 'Get cookies.txt LOCALLY'\n"
        "  2. Log in to tiktok.com in your browser\n"
        "  3. Navigate to tiktok.com and export cookies\n"
        "  4. Save the exported file or copy the contents\n"
    ),
    "twitter": (
        "X/Twitter cookie export instructions:\n"
        "  1. Install a browser extension like 'Get cookies.txt LOCALLY'\n"
        "  2. Log in to x.com in your browser\n"
        "  3. Navigate to x.com and export cookies\n"
        "  4. Save the exported file or copy the contents\n"
    ),
    "x": (
        "X/Twitter cookie export instructions:\n"
        "  1. Install a browser extension like 'Get cookies.txt LOCALLY'\n"
        "  2. Log in to x.com in your browser\n"
        "  3. Navigate to x.com and export cookies\n"
        "  4. Save the exported file or copy the contents\n"
    ),
}


def setup_platform_auth(platform: str) -> None:
    """Interactive guided cookie import for a platform.

    Prompts the user to paste cookie content or provide a path to a
    Netscape-format cookies.txt file, then saves parsed cookies as JSON.
    """
    platform = platform.lower()
    if platform not in _PLATFORM_DOMAINS:
        print(f"Cookie-based auth not needed for '{platform}'.")
        return

    print(f"\n--- Cookie Setup for {platform.title()} ---\n")
    print(_EXPORT_INSTRUCTIONS.get(platform, ""))
    print(
        "Paste the contents of your cookies.txt below,\n"
        "or enter a file path to a cookies.txt file.\n"
        "When pasting, press Enter then Ctrl-D (EOF) when done.\n"
    )

    user_input = _read_user_input()
    user_input = user_input.strip()

    # Check if input is a file path
    candidate_path = Path(user_input)
    if candidate_path.exists() and candidate_path.is_file():
        raw = candidate_path.read_text()
    else:
        raw = user_input

    cookies = _parse_netscape_cookies(raw)
    if not cookies:
        print("No valid cookies found. Please check the format and try again.")
        return

    # Filter to platform-relevant domains
    domains = _PLATFORM_DOMAINS[platform]
    platform_cookies = [
        c for c in cookies if c.get("domain", "") in domains
    ]
    if not platform_cookies:
        # If strict filtering yields nothing, keep all parsed cookies
        platform_cookies = cookies

    save_path = _save_cookies(platform, platform_cookies)
    print(f"\nSaved {len(platform_cookies)} cookies to {save_path}")


def _read_user_input() -> str:
    """Read multiline input from stdin until EOF."""
    lines: list[str] = []
    try:
        for line in sys.stdin:
            lines.append(line)
    except EOFError:
        pass
    return "".join(lines)


def _parse_netscape_cookies(raw: str) -> list[dict]:
    """Parse Netscape/Mozilla cookies.txt format into Playwright-compatible dicts."""
    cookies: list[dict] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 7:
            continue

        domain, _flag, path, secure, expires, name, value = parts[:7]
        cookie: dict = {
            "name": name,
            "value": value,
            "domain": domain,
            "path": path,
            "secure": secure.upper() == "TRUE",
            "httpOnly": False,
        }
        try:
            exp = int(expires)
            if exp > 0:
                cookie["expires"] = exp
        except ValueError:
            pass

        cookies.append(cookie)

    return cookies


def _save_cookies(platform: str, cookies: list[dict]) -> Path:
    """Save cookies list as JSON to ~/.broadside/cookies/<platform>.json."""
    _COOKIES_DIR.mkdir(parents=True, exist_ok=True)
    path = _COOKIES_DIR / f"{platform}.json"
    with open(path, "w") as f:
        json.dump(cookies, f, indent=2)
    return path


def load_cookies(platform: str) -> list[dict]:
    """Load saved cookies for a platform. Returns empty list if none saved."""
    path = _COOKIES_DIR / f"{platform}.json"
    if not path.exists():
        return []
    with open(path) as f:
        return json.load(f)


async def inject_cookies(context: BrowserContext, platform: str) -> None:
    """Add saved cookies to a Playwright browser context.

    Raises FileNotFoundError if no cookies are saved for the platform.
    Call ``setup_platform_auth`` first to create the cookie file.
    """
    cookies = load_cookies(platform)
    if not cookies:
        raise FileNotFoundError(
            f"No cookies found for {platform}. "
            f"Run 'broadside auth {platform}' to set up cookie-based authentication."
        )
    await context.add_cookies(cookies)
