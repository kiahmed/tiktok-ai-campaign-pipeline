"""OpenAI implementation of the ScriptGenerator interface.

Demonstrates the swap-a-provider story: identical contract to Gemini, only the
HTTP details differ. Uses the Chat Completions REST endpoint via ``requests``.
"""
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

logger = logging.getLogger("provider.openai")

_URL = "https://api.openai.com/v1/chat/completions"


class OpenAIScriptProvider(ScriptGenerator):
    name = "openai"

    def __init__(self, api_key: str, model: str = "gpt-4o-mini", timeout: int = 60) -> None:
        if not api_key:
            raise ConfigurationError("OPENAI_API_KEY is not set")
        self._api_key = api_key
        self._model = model
        self._timeout = timeout

    def generate(self, product: ProductInput) -> ScriptResult:
        logger.info("Generating script with OpenAI model=%s", self._model)
        raw = self.complete(SYSTEM_INSTRUCTION, build_script_prompt(product))
        text = clean_script(raw)
        if not text:
            raise ScriptGenerationError("OpenAI returned an empty script", provider=self.name)
        return ScriptResult(text=text, provider=self.name, model=self._model)

    @translate_network_errors(ScriptGenerationError)
    @with_retry()
    def complete(self, system: str, user: str, *, max_tokens: int = 512) -> str:
        """LLMProvider transport: arbitrary system+user -> raw text."""
        payload = {
            "model": self._model,
            "temperature": 0.9,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        resp = requests.post(
            _URL,
            headers={"Authorization": f"Bearer {self._api_key}"},
            json=payload,
            timeout=self._timeout,
        )
        if resp.status_code >= 400:
            raise ScriptGenerationError(
                f"HTTP {resp.status_code}: {resp.text[:300]}", provider=self.name
            )
        data = resp.json()
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ScriptGenerationError(
                f"Unexpected OpenAI response shape: {data}", provider=self.name
            ) from exc
