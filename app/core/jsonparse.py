"""Tolerant JSON extraction from LLM output.

Models sometimes wrap JSON in ```code fences``` or add a sentence before/after.
This pulls out the first valid JSON object. Shared by the Strategist and the
QC judge so both parse model output the same way.
"""
from __future__ import annotations

import json
import re

_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


def extract_json(raw: str) -> dict | None:
    """Return the first JSON object found in ``raw``, or None if unparseable."""
    if not raw:
        return None
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if "{" in text:
            text = text[text.find("{"):]
    try:
        result = json.loads(text)
        return result if isinstance(result, dict) else None
    except json.JSONDecodeError:
        pass
    match = _JSON_BLOCK.search(text)
    if not match:
        return None
    try:
        result = json.loads(match.group(0))
        return result if isinstance(result, dict) else None
    except json.JSONDecodeError:
        return None
