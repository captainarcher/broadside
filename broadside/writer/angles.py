"""Pass 1 -- Angle mining: extract satirical angles from a news story."""

from __future__ import annotations

from broadside.config import ComedyConfig
from broadside.llm import chat

# Story archetypes from BENN_VOICE.md section 6
STORY_ARCHETYPES = (
    "absurd-money",
    "product-launch",
    "AI-does-human-thing",
    "company-behaving-weirdly",
    "study-report",
    "tech-failure",
)

SYSTEM_PROMPT = """\
You are a veteran comedy writer's room researcher.  Your job is to find
the funniest, sharpest satirical ANGLES hidden inside a news story.

An angle is NOT a joke.  It is an observation, irony, or absurdity that
a joke can later be built on.  Think of it as the comedic thesis statement.

DO:
- Find genuine irony, hypocrisy, and absurdity in the facts.
- Look for contrasts (what they said vs what they did, expectation vs reality).
- Identify relatable everyday-life parallels.
- Notice buried details that are funnier than the headline.
- Find the "say the quiet part loud" angle.

DON'T:
- Write jokes, punchlines, or setups.  Angles only.
- Include political commentary, partisan framing, or moralising.
- Explain why something is funny.
- Offer more than 12 angles or fewer than 8.

FIRST LINE: Tag the story archetype as one of: absurd-money / product-launch / \
AI-does-human-thing / company-behaving-weirdly / study-report / tech-failure

Format: ARCHETYPE: <tag>

Then return a numbered list of angles, one per line.\
"""


def mine_angles(
    headline: str,
    summary: str,
    url: str,
    key_quotes: list[str],
    *,
    config: ComedyConfig,
) -> list[str]:
    """Call Claude to extract 8-12 satirical angles from a story.

    Returns a list of angle strings, stripped of numbering.
    The first element is always the archetype tag (prefixed with "ARCHETYPE:").
    """
    quotes_block = "\n".join(f'  - "{q}"' for q in key_quotes) if key_quotes else "  (none)"
    user_message = (
        f"HEADLINE: {headline}\n\n"
        f"SUMMARY:\n{summary}\n\n"
        f"SOURCE URL: {url}\n\n"
        f"KEY QUOTES:\n{quotes_block}"
    )

    raw_text = chat(
        model=config.model_angles,
        messages=[{"role": "user", "content": user_message}],
        system=SYSTEM_PROMPT,
        max_tokens=1500,
    )
    angles: list[str] = []
    for line in raw_text.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        # Preserve the archetype tag line as-is
        if line.upper().startswith("ARCHETYPE:"):
            angles.insert(0, line)
            continue
        # Strip leading numbering like "1.", "1)", "1 -", etc.
        cleaned = line.lstrip("0123456789").lstrip(".)-: ").strip()
        if cleaned:
            angles.append(cleaned)
    return angles
