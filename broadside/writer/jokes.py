"""Pass 2 -- Joke generation: turn selected angles into Benn Stone reactions."""

from __future__ import annotations

import json

from broadside.config import ComedyConfig
from broadside.llm import chat
from broadside.writer.character import load_voice_spec

# Lore registry items for inclusion in the system prompt
_LORE_REGISTRY = """\
LORE REGISTRY (use; never explain):
- The bar: Benn's wound. First person always. Sold; buyer "mostly paid for the ice machine." Eleven-word closing notice taped to the door.
- The ice machine: The only part of the business anyone valued. It knew things.
- Gary: Rival who dropped wings to five cents ("Volume."). His place is now Gary's Mattress Barn, fourteen locations. Recurring sponsor/antagonist.
- Kevin: Bar patron of legendary pettiness, now loose in the modern economy. HARD QUOTA: once per calendar week.
- The fan: NEVER named, only orbited ("a mechanical reason," "nothing fell from the ceiling," "sealed"). Max one orbit per week.
- The John Grisham: Three years, page forty. Courtroom scenes require a little walk.
- Marty Tate: The role. Benn cites it as credentials for everything. "Critics called the performance 'audible.'"
- The network: Owns his best work. Notice 88-C. Bitter reverence.
- Sponsors: All fictional; Benn sincerely believes in each. He has met Dave.
"""

_SURVIVED_EXEMPLARS = """\
SURVIVED the kill floor (generate like these):
- "When I sold my bar, the buyer told me, to my face, that he was mostly paying for the ice machine."
- "That is the most anyone has paid for anything in NFL history. Second place is whatever DirecTV charged my bar for the Sunday package."
- "My bar went for less than the away team's laundry budget, and I've made peace with that. [beat] I have not."
- "We both cried at the closing. One of us into a much better car."
- "The bar across the street went to five cents a wing. I called over there. Gary said one word to me: volume. Gary's place is a mattress store now."
- "Same bottle, two shelves. The top shelf had a little light on it. That's what you're paying for. The little light."
- "I extended happy hour to nine once. Then to close. Then it was just... the price."
- "The last free thing my bar gave out was the peanuts, and a man named Kevin filled a duffel bag."
"""

_KILLED_EXEMPLARS = """\
KILLED by the human (NEVER generate like these):
- "You don't buy a team to fix things. You buy it so no one can ask you to." -- generic rich-people cynicism; any pundit could say it.
- "Rich people pay for the right to be blamed." -- social commentary; no bar, no object, no Benn.
- "It was a boat." -- off-lore prop; Benn's wound is the bar, not a boat.
- "That's not artificial intelligence, that's artificial pricing." -- pun-as-joke; joke-shaped, empty.
"""

SYSTEM_PROMPT = """\
You are generating Benn Stone reactions for a satirical news show called Broadside.

THE LAW OF BENN (hard constraints -- a joke survives ONLY if ALL hold):
1. It could only come from Benn. If any host could read it, kill it.
2. The comedy is the bar wound expressed through ONE hyper-specific mundane object (an ice machine, a Sunday package invoice, a laundry budget, a coffee can behind the bourbon). Specificity is the engine.
3. Composure cracks quietly, never breaks. "I've made peace with it. [beat] I have not." Never yelling, never self-pity monologue.
4. The FACT line is stated straight and true. Benn's reaction is the joke; the news is never distorted.
5. BANNED: wordplay/puns as the joke itself; generic cynicism about rich people, corporations, or "society"; social commentary; any joke whose engine is "capitalism, am I right."
6. BANNED TOPICS: politics, government, elections, tragedy, layoffs-as-suffering, security scares.

REGISTER (triangulated, in order of weight):
- Steve Carell: earnest obliviousness. Emotionally invested, doesn't know he's the joke.
- Jon Stewart: incredulity at the actual news. The FACT is the absurd thing; Benn is the sane man wounded by it.
- Seth Rogen: conversational rhythm. Talking, not delivering jokes.

{lore_registry}

{survived_exemplars}

{killed_exemplars}

GENERATION RULES:
- Generate exactly EIGHT candidate reactions per angle.
- Each reaction should be 2-4 conversational sentences.
- Punch is usually the LAST short sentence.
- Mark intentional beats as [beat].
- Use different lore anchors across the eight -- vary the object.
- Numbers written out in full ("nine point six billion dollars").

Return valid JSON:
{{
  "angle_reactions": {{
    "<angle text>": [
      {{"reaction": "<full reaction text>", "lore_anchor": "<lore element used>"}},
      ...
    ],
    ...
  }}
}}
Return ONLY the JSON object, no markdown fences, no commentary.\
"""


def generate_jokes(
    angles: list[str],
    *,
    config: ComedyConfig,
) -> dict[str, list[dict[str, str]]]:
    """Generate 8 Benn Stone reaction candidates per angle.

    *angles* should be 2-3 selected angles from the mining pass.
    Returns ``{angle_text: [{reaction, lore_anchor}, ...]}``.
    """
    if not angles:
        raise ValueError("At least one angle is required")

    # Filter out archetype tag line if present
    content_angles = [a for a in angles if not a.upper().startswith("ARCHETYPE:")]
    if not content_angles:
        raise ValueError("No content angles provided (only archetype tag found)")

    system = SYSTEM_PROMPT.format(
        lore_registry=_LORE_REGISTRY,
        survived_exemplars=_SURVIVED_EXEMPLARS,
        killed_exemplars=_KILLED_EXEMPLARS,
    )

    angles_block = "\n".join(f"{i}. {a}" for i, a in enumerate(content_angles, 1))
    user_message = f"ANGLES:\n{angles_block}"

    raw = chat(
        model=config.model_jokes,
        messages=[{"role": "user", "content": user_message}],
        system=system,
        max_tokens=4000,
    ).strip()
    # Strip markdown fences if the model wraps them anyway
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1]
    if raw.endswith("```"):
        raw = raw.rsplit("```", 1)[0]

    data = json.loads(raw)
    result = data.get("angle_reactions", data.get("angle_jokes", data))

    # Normalize to the expected format for downstream consumers
    # Convert {reaction, lore_anchor} to {structure, joke} for backward compat
    normalized: dict[str, list[dict[str, str]]] = {}
    for angle_key, variants in result.items():
        normalized[angle_key] = []
        for v in variants:
            if "reaction" in v:
                normalized[angle_key].append({
                    "structure": v.get("lore_anchor", "benn-reaction"),
                    "joke": v["reaction"],
                })
            else:
                normalized[angle_key].append(v)
    return normalized
