"""Pass 3 -- Script assembly: structure reactions into Broadside episode skeleton."""

from __future__ import annotations

import json
from datetime import date

from broadside.config import ComedyConfig
from broadside.llm import chat
from broadside.schema import Episode, SourceStory

SYSTEM_PROMPT = """\
You are a comedy show-runner assembling a Broadside episode from Benn Stone's
candidate reactions.  Follow the episode skeleton EXACTLY:

EPISODE SKELETON (in order):
1. intro      -- Benn introduces himself and the show (1 sentence).
2. fact_1     -- FACT stated straight and true. No comedy. Source cited.
3. reaction_1 -- Benn's reaction (2-4 sentences, punch last). Mark [beat] pauses.
4. fact_2     -- Second FACT beat, straight.
5. reaction_2 -- Benn's second reaction.
6. sponsor    -- Fictional sponsor read. Benn believes. Real-ad tropes played
                 straight + one absurd premise + one escalation.
7. signoff    -- "I'm Benn Stone, and that's the BS."

RULES:
- FACT lines must be stated neutrally and accurately. Never distort.
- Reactions are conversational (2-4 sentences). Punch is the LAST short sentence.
- Mark intentional pauses as [beat] -- the renderer converts them.
- Numbers written out in full for the avatar.
- Total word count: 150-220 words (targets sixty to ninety seconds).
- Vary sentence length for comedic timing.

FOR EACH BEAT: select your top candidate reaction, but also list the runner-up
alternates so the human kill-floor can swap.

Return valid JSON:
{{
  "episode_id": "<generated-id>",
  "caption_hook": "<social media caption, max 100 chars>",
  "beats": [
    {{
      "id": "<skeleton-position>",
      "type": "<intro|fact|reaction|sponsor|signoff>",
      "text": "<spoken text -- top pick>",
      "alternates": ["<alt 1>", "<alt 2>", ...]
    }},
    ...
  ],
  "word_count": <int>,
  "estimated_duration_sec": <float>
}}
Return ONLY JSON. No markdown fences, no commentary.\
"""


def assemble_script(
    jokes: dict[str, list[dict[str, str]]],
    source_story: SourceStory,
    *,
    config: ComedyConfig,
    show: str = "bs",
) -> Episode:
    """Assemble selected reactions into a structured Episode draft.

    Follows the Broadside episode skeleton: intro -> FACT -> reaction -> FACT
    -> reaction -> sponsor -> signoff.

    Returns a validated Episode pydantic model.  The raw alternates are stored
    in the episode metadata for the human kill-floor pass.
    """
    # Flatten jokes for the prompt
    joke_lines: list[str] = []
    for angle, variants in jokes.items():
        joke_lines.append(f"ANGLE: {angle}")
        for i, v in enumerate(variants, 1):
            label = v.get("structure", "unknown")
            joke_lines.append(f"  [{i}. {label}] {v['joke']}")
    jokes_block = "\n".join(joke_lines)

    user_message = (
        f"SOURCE STORY:\n"
        f"  Headline: {source_story.headline}\n"
        f"  Source: {source_story.source}\n"
        f"  URL: {source_story.url}\n\n"
        f"AVAILABLE REACTIONS (8 per angle -- pick best, list alternates):\n"
        f"{jokes_block}\n\n"
        f"Target duration: {config.duration_target} seconds.\n"
        f"Today's date: {date.today().isoformat()}"
    )

    raw = chat(
        model=config.model_assembly,
        messages=[{"role": "user", "content": user_message}],
        system=SYSTEM_PROMPT,
        max_tokens=2500,
    ).strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1]
    if raw.endswith("```"):
        raw = raw.rsplit("```", 1)[0]

    data = json.loads(raw)

    # Convert beats format to scenes for Episode model compatibility
    beats = data.get("beats", data.get("scenes", []))
    scenes = []
    for beat in beats:
        scene_data: dict = {
            "id": beat["id"],
            "type": beat.get("type", "talk"),
            "text": beat["text"],
        }
        # Store alternates in metadata (preserved through Episode model)
        if beat.get("alternates"):
            scene_data["alternates"] = beat["alternates"]
        scenes.append(scene_data)

    episode = Episode(
        episode=data.get("episode_id", f"bs-{date.today().strftime('%Y%m%d')}"),
        show=show,
        caption_hook=data.get("caption_hook", ""),
        source_story=source_story,
        scenes=scenes,
    )
    return episode
