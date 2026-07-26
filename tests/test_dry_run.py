"""Tests for dry-run mode — validates inputs, prints plan, zero network calls."""

from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from broadside.cli import cli


FIXTURES = Path(__file__).parent / "fixtures"


def test_scout_dry_run():
    runner = CliRunner()
    result = runner.invoke(cli, ["scout", "--dry-run"], catch_exceptions=False)
    assert result.exit_code == 0
    assert "DRY RUN" in result.output
    assert "Reddit" in result.output
    assert "Hacker News" in result.output
    assert "No network calls" in result.output


def test_render_dry_run():
    runner = CliRunner()
    ep_path = str(FIXTURES / "ep-test-three-scenes.yaml")
    result = runner.invoke(
        cli,
        ["render", ep_path, "--dry-run"],
        catch_exceptions=False,
    )
    assert result.exit_code == 0
    assert "DRY RUN" in result.output
    assert "Talk scenes to render" in result.output
    assert "Estimated cost" in result.output
    assert "No API calls" in result.output
