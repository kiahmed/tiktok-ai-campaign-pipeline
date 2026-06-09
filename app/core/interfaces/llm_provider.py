from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class LLMProvider(Protocol):
    """Low-level text-completion transport to an LLM vendor.

    This is the *transport* abstraction (separate from the higher-level
    ``ScriptGenerator``): given a system + user message, return the model's raw
    text. The Creative Strategist uses it to send rich, dynamically-built
    prompts and parse structured JSON back. Gemini / OpenAI / Claude providers
    all satisfy it, so swapping the LLM stays a configuration change.
    """

    name: str

    def complete(self, system: str, user: str) -> str:
        """Return the model's text response for the given system+user prompt."""
        ...
