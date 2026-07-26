"""Guided onboarding for Broadside — walks through account setup and verification."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import click


STEPS = [
    {
        "name": "HeyGen",
        "env_var": "HEYGEN_API_KEY",
        "instructions": [
            "Sign up at https://heygen.com",
            "Go to Settings > API",
            "Create an API key",
            "Fund your API wallet (pay-as-you-go)",
            "Add HEYGEN_API_KEY to your .env file",
        ],
    },
    {
        "name": "Replicate",
        "env_var": "REPLICATE_API_TOKEN",
        "instructions": [
            "Sign up at https://replicate.com",
            "Go to Account > API Tokens",
            "Create a token",
            "Add a payment method in Billing",
            "Add REPLICATE_API_TOKEN to your .env file",
        ],
    },
    {
        "name": "ElevenLabs",
        "env_var": "ELEVENLABS_API_KEY",
        "instructions": [
            "Sign up at https://elevenlabs.io",
            "Go to Profile > API Keys",
            "Create an API key",
            "Browse Voice Library for a dramatic announcer voice",
            "Note the voice_id and add to config.yaml under ads.voice_id",
            "Add ELEVENLABS_API_KEY to your .env file",
        ],
    },
    {
        "name": "OpenRouter (LLM gateway)",
        "env_var": "OPENROUTER_API_KEY",
        "instructions": [
            "Go to https://openrouter.ai",
            "Sign in and go to Settings > Keys",
            "Create an API key",
            "Add OPENROUTER_API_KEY to your .env file",
            "Ensure your account has credit balance for model usage",
        ],
    },
    {
        "name": "Descript",
        "env_var": "DESCRIPT_API_TOKEN",
        "instructions": [
            "Sign up for a paid Descript plan at https://descript.com",
            "Go to Settings > API Tokens",
            "Create a token (note: tokens are scoped to a specific Drive)",
            "Add DESCRIPT_API_TOKEN to your .env file",
        ],
    },
    {
        "name": "YouTube",
        "env_var": "GOOGLE_CLIENT_ID",
        "instructions": [
            "Go to https://console.cloud.google.com",
            "Create a new project",
            "Enable YouTube Data API v3",
            "Create OAuth 2.0 credentials (Desktop app type)",
            "Add yourself as a test user in the consent screen",
            "Add GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET to your .env file",
            "Run: broadside auth setup youtube",
        ],
    },
    {
        "name": "X / Twitter",
        "env_var": "TWITTER_API_KEY",
        "instructions": [
            "Apply for a developer account at https://developer.x.com",
            "Create a project and app with Read+Write permissions",
            "Generate API Key, API Secret, Access Token, and Access Secret",
            "Add TWITTER_API_KEY, TWITTER_API_SECRET, TWITTER_ACCESS_TOKEN, TWITTER_ACCESS_SECRET to .env",
        ],
    },
    {
        "name": "Instagram (cookies)",
        "env_var": None,
        "instructions": [
            "Log into Instagram in your browser",
            "Install a cookie export extension (e.g., 'Get cookies.txt LOCALLY')",
            "Export cookies for instagram.com",
            "Run: broadside auth setup instagram",
        ],
    },
    {
        "name": "TikTok (cookies)",
        "env_var": None,
        "instructions": [
            "Log into TikTok in your browser",
            "Install a cookie export extension (e.g., 'Get cookies.txt LOCALLY')",
            "Export cookies for tiktok.com",
            "Run: broadside auth setup tiktok",
        ],
    },
    {
        "name": "Reddit",
        "env_var": None,
        "instructions": [
            "No setup needed — Broadside uses Reddit's public RSS feeds",
            "Subreddits are configured in config.yaml under news.sources.reddit",
        ],
    },
    {
        "name": "NewsData.io",
        "env_var": "NEWSDATA_API_KEY",
        "instructions": [
            "Sign up at https://newsdata.io",
            "Get your free API key from the dashboard",
            "Add NEWSDATA_API_KEY to your .env file",
        ],
    },
    {
        "name": "FFmpeg",
        "env_var": None,
        "check_command": "ffmpeg -version",
        "instructions": [
            "Install ffmpeg: brew install ffmpeg (macOS) or apt install ffmpeg (Linux)",
        ],
    },
]


def run_onboarding() -> None:
    click.echo("=" * 60)
    click.echo("  BROADSIDE ONBOARDING")
    click.echo("  Setting up accounts and API access")
    click.echo("=" * 60)
    click.echo()

    completed = 0
    skipped = 0

    for i, step in enumerate(STEPS, 1):
        click.echo(f"\n── Step {i}/{len(STEPS)}: {step['name']} ──\n")

        # Check if already configured
        if step.get("env_var") and os.environ.get(step["env_var"]):
            click.echo(f"  [+] {step['env_var']} is already set.")
            completed += 1
            continue

        if step.get("check_command"):
            binary = step["check_command"].split()[0]
            if shutil.which(binary):
                click.echo(f"  [+] {binary} is installed.")
                completed += 1
                continue

        # Show instructions
        for instruction in step["instructions"]:
            click.echo(f"  {instruction}")

        click.echo()
        if click.confirm("  Mark as done?", default=False):
            # Verify if possible
            if step.get("env_var"):
                val = os.environ.get(step["env_var"])
                if val:
                    click.echo(f"  [+] Verified: {step['env_var']} is set.")
                    completed += 1
                else:
                    click.echo(f"  [-] {step['env_var']} not found in environment.")
                    click.echo("      Set it and re-run onboard to verify.")
                    skipped += 1
            else:
                completed += 1
        else:
            skipped += 1
            click.echo("  Skipped. You can re-run `broadside onboard` later.")

    click.echo(f"\n{'=' * 60}")
    click.echo(f"  Onboarding complete: {completed} done, {skipped} remaining")
    click.echo(f"{'=' * 60}")

    if skipped:
        click.echo("\nRemaining steps:")
        click.echo("  1. Set missing environment variables in your .env file")
        click.echo("  2. Add style reference images to assets/style-references/")
        click.echo("  3. Add example scripts to examples/")
        click.echo("  4. Fill in config.yaml with avatar and voice IDs")
        click.echo("  5. Run `broadside auth check` to verify everything")
    else:
        click.echo("\nAll set! Try: broadside scout --dry-run")
