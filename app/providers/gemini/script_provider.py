"""Gemini implementation of the ScriptGenerator interface.

Talks to the Google Generative Language REST API directly with ``requests`` so
there is no heavy SDK dependency. Any transport-level error is retried; any
definitive failure is surfaced as a domain ``ScriptGenerationError``.
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

logger = logging.getLogger("provider.gemini")

_BASE = "https://generativelanguage.googleapis.com/v1beta/models"


class GeminiScriptProvider(ScriptGenerator):
    name = "gemini"

    def __init__(self, api_key: str, model: str = "gemini-2.0-flash", timeout: int = 60) -> None:
        if not api_key:
            raise ConfigurationError("GEMINI_API_KEY is not set")
        self._api_key = api_key
        self._model = model
        self._timeout = timeout

    def generate(self, product: ProductInput) -> ScriptResult:
        logger.info("Generating script with Gemini model=%s", self._model)
        raw = self.complete(SYSTEM_INSTRUCTION, build_script_prompt(product))
        text = clean_script(raw)
        if not text:
            raise ScriptGenerationError("Gemini returned an empty script", provider=self.name)
        return ScriptResult(text=text, provider=self.name, model=self._model)

    @translate_network_errors(ScriptGenerationError)
    @with_retry()
    def complete(self, system: str, user: str, *, max_tokens: int = 1024) -> str:
        """LLMProvider transport: arbitrary system+user -> raw text."""
        url = f"{_BASE}/{self._model}:generateContent"
        gen_config: dict = {"temperature": 0.9, "maxOutputTokens": max_tokens}
        # Gemini 2.5+/3.x "flash" are thinking models: by default they spend
        # output tokens on reasoning, which truncates short structured answers.
        # Disable thinking for these fast script/JSON calls. Harmless on models
        # that don't support it.
        gen_config["thinkingConfig"] = {"thinkingBudget": 0}
        payload = {
            "system_instruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": gen_config,
        }
        resp = requests.post(
            url,
            params={"key": self._api_key},
            json=payload,
            timeout=self._timeout,
        )
        if resp.status_code >= 400:
            raise ScriptGenerationError(
                f"HTTP {resp.status_code}: {resp.text[:300]}", provider=self.name
            )
        data = resp.json()
        try:
            # Join all text parts (a thinking model may emit multiple parts).
            parts = data["candidates"][0]["content"]["parts"]
            text = "".join(p.get("text", "") for p in parts)
            if not text:
                raise KeyError("no text parts")
            return text
        except (KeyError, IndexError, TypeError) as exc:
            raise ScriptGenerationError(
                f"Unexpected Gemini response shape: {data}", provider=self.name
            ) from exc
