"""Anthropic Claude implementation of the ScriptGenerator interface."""
from __future__ import annotations

import logging

import requests

from app.core.entities import ProductInput, ScriptResult
from app.core.exceptions import ConfigurationError, ScriptGenerationError
from app.core.http import translate_network_errors
from app.core.interfaces import ScriptGenerator
from app.core.retry import with_retry
from app.providers.prompt import (
    SYSTEM_INSTRUCTION,
    build_script_prompt,
    clean_script,
)

logger = logging.getLogger("provider.claude")

_URL = "https://api.anthropic.com/v1/messages"
_API_VERSION = "2023-06-01"


class ClaudeScriptProvider(ScriptGenerator):
    name = "claude"

    def __init__(self, api_key: str, model: str = "claude-sonnet-4-6", timeout: int = 60) -> None:
        if not api_key:
            raise ConfigurationError("CLAUDE_API_KEY is not set")
        self._api_key = api_key
        self._model = model
        self._timeout = timeout

    def generate(self, product: ProductInput) -> ScriptResult:
        logger.info("Generating script with Claude model=%s", self._model)
        raw = self.complete(SYSTEM_INSTRUCTION, build_script_prompt(product))
        text = clean_script(raw)
        if not text:
            raise ScriptGenerationError("Claude returned an empty script", provider=self.name)
        return ScriptResult(text=text, provider=self.name, model=self._model)

    @translate_network_errors(ScriptGenerationError)
    @with_retry()
    def complete(self, system: str, user: str, *, max_tokens: int = 512) -> str:
        """LLMProvider transport: arbitrary system+user -> raw text."""
        payload = {
            "model": self._model,
            "max_tokens": max_tokens,
            "temperature": 0.9,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        resp = requests.post(
            _URL,
            headers={
                "x-api-key": self._api_key,
                "anthropic-version": _API_VERSION,
                "content-type": "application/json",
            },
            json=payload,
            timeout=self._timeout,
        )
        if resp.status_code >= 400:
            raise ScriptGenerationError(
                f"HTTP {resp.status_code}: {resp.text[:300]}", provider=self.name
            )
        data = resp.json()
        try:
            return data["content"][0]["text"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ScriptGenerationError(
                f"Unexpected Claude response shape: {data}", provider=self.name
            ) from exc
