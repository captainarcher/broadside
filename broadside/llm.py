"""Shared LLM client using OpenRouter (OpenAI-compatible API).

All LLM calls in Broadside go through this module. OpenRouter provides
access to Claude, GPT, Gemini, and other models via a unified API.
Uses the OpenAI Python SDK with a custom base_url.
"""

from __future__ import annotations

import os

from openai import OpenAI


def get_client() -> OpenAI:
    """Create an OpenRouter-backed OpenAI client.

    Requires OPENROUTER_API_KEY environment variable.
    """
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key:
        raise EnvironmentError(
            "OPENROUTER_API_KEY environment variable is required. "
            "Get your key at https://openrouter.ai/settings/keys"
        )
    return OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=api_key,
        default_headers={
            "X-Title": "Broadside",
        },
    )


def chat(
    model: str,
    messages: list[dict[str, str]],
    *,
    system: str | None = None,
    max_tokens: int = 2048,
) -> str:
    """Send a chat completion request and return the text response.

    Args:
        model: OpenRouter model ID (e.g., "anthropic/claude-sonnet-4.6")
        messages: List of message dicts with "role" and "content"
        system: Optional system prompt (prepended as a system message)
        max_tokens: Maximum tokens in response

    Returns:
        The assistant's response text.
    """
    client = get_client()

    full_messages = []
    if system:
        full_messages.append({"role": "system", "content": system})
    full_messages.extend(messages)

    response = client.chat.completions.create(
        model=model,
        messages=full_messages,
        max_tokens=max_tokens,
    )
    return response.choices[0].message.content or ""
