"""Pass 4 -- Voice polish: rewrite script in Benn Stone's voice using full spec."""

from __future__ import annotations

from pathlib import Path

import yaml

from broadside.config import ComedyConfig
from broadside.llm import chat
from broadside.schema import Episode
from broadside.writer.character import (
    format_character_context,
    load_character_sheet,
    load_example_bank,
    load_voice_spec,
)

SYSTEM_PROMPT_TEMPLATE = """\
You are performing the final voice-polish pass on a Broadside episode script.
Your ONLY job is to rewrite every scene's spoken text so it sounds exactly
like Benn Stone -- same vocabulary, same cadence, same attitude.

The voice system spec and character sheet below define the voice.  The spec
is the authoritative source.  Study it before rewriting.

{character_context}

REGISTER TRIANGULATION (apply in this order of weight):
1. Steve Carell: earnest obliviousness. Emotionally invested, doesn't know he's the joke.
2. Jon Stewart: incredulity at the actual news. The FACT is the absurd thing; Benn is the sane man wounded by it.
3. Seth Rogen: conversational rhythm. Talking, not delivering jokes.

RULES:
- Preserve the beat structure (scene IDs and order).  Do NOT add or
  remove scenes.
- Rewrite the "text" field of each scene.  Everything else stays.
- Match Benn's sentence length patterns and rhythm from the exemplars.
- Keep punchlines SHORTER than setups.
- Composure cracks quietly, never breaks.
- Mark intentional pauses as [beat].
- Numbers written out in full for the avatar.
- Total word count must stay between 150-220 words.

DO:
- Use Benn's specific verbal tics and transition phrases from the spec.
- Maintain joke structure -- don't soften punchlines.
- Read each line out loud in your head -- it must sound natural spoken.
- The FACT lines stay straight and true. Only reactions get voice.

DON'T:
- Moralise, editorialize, or add disclaimers.
- Explain jokes or add "get it?" asides.
- Change scene IDs or types.
- Add stage directions or parentheticals (except [beat]).
- Use political framing.
- Exceed 220 words total.
- Use puns, wordplay, or generic cynicism as the joke engine.

Return valid JSON: a list of objects, each with "id" and "text" keys.
Return ONLY JSON. No markdown fences, no commentary.\
"""


def polish_script(
    episode: Episode,
    *,
    config: ComedyConfig,
) -> Episode:
    """Rewrite all talk scenes in Benn Stone's voice using Opus.

    Loads the full voice spec (BENN_VOICE.md) as primary context,
    supplemented by the YAML character sheet and example bank.
    """
    # Load voice spec as primary context
    try:
        voice_spec = load_voice_spec()
    except FileNotFoundError:
        voice_spec = None

    sheet = load_character_sheet(config.character_sheet)
    examples = load_example_bank(config.example_bank)
    char_context = format_character_context(sheet, examples, voice_spec=voice_spec)

    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(character_context=char_context)

    # Build the scenes payload for the model
    scenes_for_prompt = []
    for scene in episode.scenes:
        if hasattr(scene, "text"):
            scenes_for_prompt.append({"id": scene.id, "text": scene.text})

    user_message = (
        f"EPISODE: {episode.episode}\n\n"
        f"SCENES TO POLISH:\n{yaml.dump(scenes_for_prompt, default_flow_style=False)}"
    )

    raw = chat(
        model=config.model_polish,
        messages=[{"role": "user", "content": user_message}],
        system=system_prompt,
        max_tokens=2000,
    ).strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1]
    if raw.endswith("```"):
        raw = raw.rsplit("```", 1)[0]

    import json
    polished: list[dict[str, str]] = json.loads(raw)

    # Build a lookup of polished text by scene ID
    polished_map = {s["id"]: s["text"] for s in polished}

    # Rebuild scenes with polished text
    new_scenes = []
    for scene in episode.scenes:
        scene_data = scene.model_dump()
        if scene.id in polished_map:
            scene_data["text"] = polished_map[scene.id]
        new_scenes.append(scene_data)

    polished_episode = Episode(
        episode=episode.episode,
        show=episode.show,
        post_day=episode.post_day,
        caption_hook=episode.caption_hook,
        source_story=episode.source_story,
        scenes=new_scenes,
        end_card=episode.end_card,
    )

    return polished_episode


def save_draft(episode: Episode, drafts_dir: str | Path = "episodes/drafts") -> Path:
    """Save a polished episode as YAML in the drafts directory.

    Returns the path to the saved file.
    """
    drafts_dir = Path(drafts_dir)
    drafts_dir.mkdir(parents=True, exist_ok=True)
    path = drafts_dir / f"{episode.episode}.yaml"
    with open(path, "w") as f:
        yaml.dump(
            episode.model_dump(),
            f,
            default_flow_style=False,
            sort_keys=False,
            allow_unicode=True,
        )
    return path
