"""Broadside CLI — automated video production for satirical news shows."""

from __future__ import annotations

import sys
from pathlib import Path

import click
from dotenv import load_dotenv

# Auto-load .env from project directory
load_dotenv()

from .config import BroadsideConfig
from .budget import BudgetGuard, SpendLedger
from .schema import Episode, AdConcept


def load_config(ctx: click.Context) -> BroadsideConfig:
    config_path = ctx.obj.get("config", "config/config.yaml") if ctx.obj else "config/config.yaml"
    return BroadsideConfig.load(config_path)


@click.group()
@click.option("--config", default="config/config.yaml", help="Path to config.yaml")
@click.pass_context
def cli(ctx: click.Context, config: str) -> None:
    """Broadside — automated video production for satirical news shows."""
    ctx.ensure_object(dict)
    ctx.obj["config"] = config


# ── Scout ─────────────────────────────────────────────────────────────


@cli.command()
@click.option("--dry-run", is_flag=True, help="Preview sources, no fetching")
@click.pass_context
def scout(ctx: click.Context, dry_run: bool) -> None:
    """Run the news sourcing pipeline."""
    config = load_config(ctx)

    if dry_run:
        click.echo("DRY RUN — News sourcing plan:")
        sources = config.news.sources
        click.echo(f"  Reddit: {', '.join(sources.reddit.subreddits)}")
        click.echo(f"  Hacker News: top {sources.hackernews.top_n}")
        click.echo(f"  Google News: {', '.join(sources.google_news.topics)}")
        click.echo(f"  NewsData.io: {', '.join(sources.newsdata.categories)}")
        click.echo("  Supplementary: UPI Odd News, Ars Technica, The Verge")
        click.echo("\nNo network calls made.")
        return

    from .scout import run_scout_pipeline

    results = run_scout_pipeline(config)
    click.echo(f"\nScouted {len(results)} stories. Top candidates saved to scout-digest.json")


# ── Write ─────────────────────────────────────────────────────────────


@cli.command()
@click.argument("story", required=False)
@click.option("--batch", is_flag=True, help="Process all scouted stories")
@click.pass_context
def write(ctx: click.Context, story: str | None, batch: bool) -> None:
    """Interactive joke writing for a story."""
    config = load_config(ctx)

    if not story and not batch:
        click.echo("Provide a story URL/ID or use --batch to process all scouted stories.")
        sys.exit(1)

    from .writer import run_writing_pipeline

    if batch:
        run_writing_pipeline(config, batch_mode=True)
    else:
        run_writing_pipeline(config, story_ref=story)


# ── Illustrate ────────────────────────────────────────────────────────


@cli.command()
@click.argument("episode_yaml", type=click.Path(exists=True))
@click.pass_context
def illustrate(ctx: click.Context, episode_yaml: str) -> None:
    """Generate editorial illustrations for an episode."""
    config = load_config(ctx)
    episode = Episode.load(episode_yaml)

    from .illustrate import generate_illustrations

    paths = generate_illustrations(config, episode)
    click.echo(f"Generated {len(paths)} illustrations for {episode.episode}")


# ── Ad ────────────────────────────────────────────────────────────────


@cli.command()
@click.argument("concept_yaml", required=False, type=click.Path(exists=True))
@click.option("--random", "use_random", is_flag=True, help="Random concept from bank")
@click.pass_context
def ad(ctx: click.Context, concept_yaml: str | None, use_random: bool) -> None:
    """Generate a parody advertisement."""
    config = load_config(ctx)

    if not concept_yaml and not use_random:
        click.echo("Provide a concept YAML or use --random.")
        sys.exit(1)

    from .ads import generate_parody_ad

    if use_random:
        output = generate_parody_ad(config, random_concept=True)
    else:
        concept = AdConcept.load(concept_yaml)
        output = generate_parody_ad(config, concept=concept)

    click.echo(f"Parody ad rendered: {output}")


# ── Render ────────────────────────────────────────────────────────────


@cli.command()
@click.argument("episode_yaml", type=click.Path(exists=True))
@click.option("--dry-run", is_flag=True, help="Print plan + cost, no API calls")
@click.option("--yes", is_flag=True, help="Skip confirmation (budget rails enforced)")
@click.pass_context
def render(ctx: click.Context, episode_yaml: str, dry_run: bool, yes: bool) -> None:
    """Render episode scenes via HeyGen."""
    config = load_config(ctx)
    episode = Episode.load(episode_yaml)
    show = config.get_show(episode.show)

    from .render import plan_render, execute_render

    plan = plan_render(config, episode)

    if dry_run:
        click.echo(f"DRY RUN — Render plan for {episode.episode}:")
        click.echo(f"  Show: {episode.show}")
        click.echo(f"  Talk scenes to render: {plan.scenes_to_render}")
        click.echo(f"  Scenes already cached: {plan.scenes_cached}")
        click.echo(f"  Estimated duration: {plan.estimated_duration:.1f}s")
        click.echo(f"  Estimated cost: ${plan.estimated_cost:.2f}")
        click.echo("\nNo API calls made.")
        return

    guard = BudgetGuard(config.budget.max_batch_usd, config.budget.max_weekly_usd)
    check = guard.check_batch(plan.estimated_cost)

    if not check.allowed:
        click.echo(check.summary())
        sys.exit(1)

    if not yes:
        click.echo(f"Render plan: {plan.scenes_to_render} scenes, ~${plan.estimated_cost:.2f}")
        if not click.confirm("Proceed?"):
            click.echo("Cancelled.")
            return

    import asyncio

    result = asyncio.run(execute_render(config, episode, plan, guard))
    click.echo(f"Rendered {result.scenes_rendered} scenes, cost: ${result.total_cost:.2f}")
    click.echo(f"Manifest: {result.manifest_path}")


# ── Assemble ──────────────────────────────────────────────────────────


@cli.command()
@click.argument("episode_yaml", type=click.Path(exists=True))
@click.option(
    "--engine",
    type=click.Choice(["auto", "descript", "ffmpeg"]),
    default="auto",
    help="Assembly engine",
)
@click.pass_context
def assemble(ctx: click.Context, episode_yaml: str, engine: str) -> None:
    """Assemble final video from rendered scenes."""
    config = load_config(ctx)
    episode = Episode.load(episode_yaml)

    from .assemble import assemble_episode

    output = assemble_episode(config, episode, engine=engine)
    click.echo(f"Assembled: {output}")


# ── Publish ───────────────────────────────────────────────────────────


@cli.command()
@click.argument("episode", type=str)
@click.option("--platform", type=str, help="Comma-separated: youtube,x,instagram,tiktok")
@click.option("--all", "all_platforms", is_flag=True, help="Publish to all configured platforms")
@click.pass_context
def publish(ctx: click.Context, episode: str, platform: str | None, all_platforms: bool) -> None:
    """Publish an episode to social platforms (human-initiated)."""
    config = load_config(ctx)

    if not platform and not all_platforms:
        click.echo("Specify --platform or --all")
        sys.exit(1)

    platforms = ["youtube", "x", "instagram", "tiktok"] if all_platforms else platform.split(",")

    from .publish import publish_episode

    for plat in platforms:
        plat = plat.strip()
        click.echo(f"\n── Publishing to {plat} ──")
        if not click.confirm(f"  Confirm publish to {plat}?"):
            click.echo(f"  Skipped {plat}.")
            continue
        result = publish_episode(config, episode, plat)
        click.echo(f"  Published: {result}")


# ── Run ───────────────────────────────────────────────────────────────


@cli.command()
@click.option("--dry-run", is_flag=True, help="Preview plan, no execution")
@click.option("--yes", is_flag=True, help="Unattended mode (budget rails enforced)")
@click.pass_context
def run(ctx: click.Context, dry_run: bool, yes: bool) -> None:
    """Full pipeline: scan approved/ → render → assemble → output."""
    config = load_config(ctx)
    approved_dir = Path("episodes/approved")

    if not approved_dir.exists():
        click.echo("No episodes/approved/ directory found.")
        sys.exit(1)

    yamls = sorted(approved_dir.glob("*.yaml")) + sorted(approved_dir.glob("*.yml"))
    if not yamls:
        click.echo("No approved episodes found.")
        return

    click.echo(f"Found {len(yamls)} approved episode(s):")
    for y in yamls:
        click.echo(f"  {y.name}")

    if dry_run:
        for y in yamls:
            ctx.invoke(render, episode_yaml=str(y), dry_run=True, yes=False)
        click.echo("\nDRY RUN complete. No API calls made.")
        return

    import asyncio
    from .render import plan_render, execute_render
    from .assemble import assemble_episode

    guard = BudgetGuard(config.budget.max_batch_usd, config.budget.max_weekly_usd)

    total_cost = 0.0
    results = []

    for y in yamls:
        episode = Episode.load(y)
        click.echo(f"\n{'='*60}")
        click.echo(f"Processing: {episode.episode}")
        click.echo(f"{'='*60}")

        plan = plan_render(config, episode)

        if plan.scenes_to_render == 0:
            click.echo("  All scenes cached, skipping render.")
        else:
            check = guard.check_batch(plan.estimated_cost)
            if not check.allowed:
                click.echo(f"  BUDGET REFUSED: {check.reason}")
                results.append({"episode": episode.episode, "status": "budget_refused"})
                continue

            if not yes:
                click.echo(f"  Render: {plan.scenes_to_render} scenes, ~${plan.estimated_cost:.2f}")
                if not click.confirm("  Proceed?"):
                    click.echo("  Skipped.")
                    continue

            result = asyncio.run(execute_render(config, episode, plan, guard))
            total_cost += result.total_cost
            click.echo(f"  Rendered: {result.scenes_rendered} scenes, ${result.total_cost:.2f}")

        output = assemble_episode(config, episode, engine="auto")
        click.echo(f"  Assembled: {output}")

        # Move YAML to rendered/
        rendered_dir = Path("episodes/rendered")
        rendered_dir.mkdir(parents=True, exist_ok=True)
        dest = rendered_dir / y.name
        y.rename(dest)
        click.echo(f"  Moved {y.name} → episodes/rendered/")

        results.append({"episode": episode.episode, "status": "complete", "output": str(output)})

    # Write summary
    from datetime import date

    summary_path = Path("out") / f"SUMMARY-{date.today().isoformat()}.md"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    with open(summary_path, "w") as f:
        f.write(f"# Broadside Run Summary — {date.today()}\n\n")
        f.write(f"Episodes processed: {len(results)}\n")
        f.write(f"Total spend: ${total_cost:.2f}\n\n")
        for r in results:
            f.write(f"- **{r['episode']}**: {r['status']}\n")

    click.echo(f"\nRun complete. Summary: {summary_path}")

    # Send notifications
    from .notify import send_notifications

    send_notifications(
        config,
        subject=f"Broadside run complete — {len(results)} episodes",
        body=summary_path.read_text(),
    )


# ── Retry ─────────────────────────────────────────────────────────────


@cli.command()
@click.argument("episode_id", type=str)
@click.argument("scene_id", type=str)
@click.pass_context
def retry(ctx: click.Context, episode_id: str, scene_id: str) -> None:
    """Re-render a single scene."""
    config = load_config(ctx)
    from .render import retry_scene

    import asyncio

    result = asyncio.run(retry_scene(config, episode_id, scene_id))
    click.echo(f"Re-rendered {scene_id}: {result}")


# ── Auth ──────────────────────────────────────────────────────────────


@cli.group()
def auth() -> None:
    """Manage platform authentication."""


@auth.command("setup")
@click.argument("platform", type=click.Choice(["youtube", "x", "twitter", "instagram", "tiktok"]))
@click.pass_context
def auth_setup(ctx: click.Context, platform: str) -> None:
    """Guided auth/cookie setup for a platform."""
    from .publish.cookies import setup_platform_auth

    setup_platform_auth(platform)


@auth.command("check")
@click.pass_context
def auth_check(ctx: click.Context) -> None:
    """Verify all platform credentials."""
    import os

    click.echo("Checking credentials...\n")

    env_vars = {
        "HeyGen": "HEYGEN_API_KEY",
        "Replicate": "REPLICATE_API_TOKEN",
        "ElevenLabs": "ELEVENLABS_API_KEY",
        "OpenRouter": "OPENROUTER_API_KEY",
        "Descript": "DESCRIPT_API_TOKEN",
        "YouTube (client)": "GOOGLE_CLIENT_ID",
        "NewsData.io": "NEWSDATA_API_KEY",
    }

    for name, var in env_vars.items():
        status = "SET" if os.environ.get(var) else "MISSING"
        icon = "+" if status == "SET" else "-"
        click.echo(f"  [{icon}] {name}: {status}")

    # Check cookie files
    cookie_dir = Path.home() / ".broadside" / "cookies"
    for platform in ["twitter", "instagram", "tiktok"]:
        cookie_file = cookie_dir / f"{platform}.json"
        status = "FOUND" if cookie_file.exists() else "MISSING"
        icon = "+" if status == "FOUND" else "-"
        click.echo(f"  [{icon}] {platform.title()} cookies: {status}")


@auth.command("refresh")
@click.argument("platform", type=click.Choice(["twitter", "instagram", "tiktok"]))
@click.pass_context
def auth_refresh(ctx: click.Context, platform: str) -> None:
    """Re-import cookies for a platform."""
    from .publish.cookies import setup_platform_auth

    setup_platform_auth(platform)


# ── Budget ────────────────────────────────────────────────────────────


@cli.command("budget")
@click.option("--history", is_flag=True, help="Show weekly spend history")
def budget_cmd(history: bool) -> None:
    """Show current spend summary."""
    ledger = SpendLedger.load()

    if history:
        click.echo("Spend history (last 30 days):\n")
        for entry in reversed(ledger.entries[-50:]):
            click.echo(
                f"  {entry.timestamp[:19]}  {entry.service:12s}  "
                f"${entry.amount_usd:6.2f}  {entry.description}"
            )
        click.echo(f"\nWeekly total: ${ledger.weekly_spend():.2f}")
    else:
        click.echo(f"Today: ${ledger.today_spend():.2f}")
        click.echo(f"This week: ${ledger.weekly_spend():.2f}")
        click.echo(f"Entries (last 30 days): {len(ledger.entries)}")


# ── Install Schedule ──────────────────────────────────────────────────


@cli.command("install-schedule")
@click.pass_context
def install_schedule(ctx: click.Context) -> None:
    """Install cron/launchd/systemd schedule."""
    from .scheduler import install_schedule

    install_schedule()


# ── Onboard ───────────────────────────────────────────────────────────


@cli.command()
@click.pass_context
def onboard(ctx: click.Context) -> None:
    """Guided setup: create accounts, set API keys, verify access."""
    from .onboard import run_onboarding

    run_onboarding()
