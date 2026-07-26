"""Character sheet, voice spec, and example bank loader for comedy voice consistency."""

from __future__ import annotations

import random
from pathlib import Path

import yaml

# Default path to the comprehensive voice spec (repo root)
_DEFAULT_VOICE_SPEC_PATH = Path(__file__).resolve().parent.parent.parent / "BENN_VOICE.md"


def load_voice_spec(path: str | Path | None = None) -> str:
    """Load the full BENN_VOICE.md comedy system spec as a string.

    This is the PRIMARY character context -- it takes precedence over the
    basic YAML character sheet.  Returns the full markdown text.

    Raises FileNotFoundError if the spec file is missing.
    """
    if path is None:
        path = _DEFAULT_VOICE_SPEC_PATH
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Voice spec not found: {path}")
    return path.read_text()


def load_character_sheet(path: str | Path) -> dict:
    """Load a YAML character sheet (persona, voice traits, do/don't rules).

    Returns the raw dict so callers can inspect individual fields.
    Raises FileNotFoundError if the sheet is missing.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Character sheet not found: {path}")
    with open(path) as f:
        return yaml.safe_load(f) or {}


def load_example_bank(dir_path: str | Path, max_examples: int = 5) -> list[str]:
    """Load a random subset of example YAML scripts as raw strings.

    Scans *dir_path* for .yaml/.yml files, shuffles, and returns up to
    *max_examples* file contents.  Returns an empty list when the
    directory is missing or empty.
    """
    dir_path = Path(dir_path)
    if not dir_path.is_dir():
        return []

    files = sorted(dir_path.glob("*.yaml")) + sorted(dir_path.glob("*.yml"))
    if not files:
        return []

    selected = random.sample(files, min(max_examples, len(files)))
    examples: list[str] = []
    for fp in selected:
        examples.append(fp.read_text())
    return examples


def format_character_context(
    sheet: dict,
    examples: list[str],
    voice_spec: str | None = None,
) -> str:
    """Format voice spec + character sheet + examples into a prompt-ready block.

    The voice spec (BENN_VOICE.md) is the PRIMARY context and comes first.
    The YAML character sheet supplements it with quick-reference traits.
    Example scripts provide concrete rhythm/voice patterns.

    If *voice_spec* is None, attempts to load from default path (non-fatal
    if missing -- falls back to sheet-only mode for backward compat).
    """
    parts: list[str] = []

    # Voice spec is PRIMARY context
    if voice_spec is None:
        try:
            voice_spec = load_voice_spec()
        except FileNotFoundError:
            voice_spec = None

    if voice_spec:
        parts.append("=== VOICE SYSTEM SPEC (PRIMARY -- this defines the character) ===")
        parts.append(voice_spec.strip())
        parts.append("")

    parts.append("=== CHARACTER SHEET (quick reference) ===")
    parts.append(yaml.dump(sheet, default_flow_style=False, sort_keys=False).strip())

    if examples:
        parts.append("")
        parts.append("=== EXAMPLE SCRIPTS (study voice, rhythm, and joke structure) ===")
        for i, ex in enumerate(examples, 1):
            parts.append(f"--- Example {i} ---")
            parts.append(ex.strip())

    return "\n".join(parts)
