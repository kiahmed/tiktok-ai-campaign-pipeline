"""Shared prompt construction for TikTok ad scripts.

Kept provider-neutral so every ScriptGenerator (Gemini, OpenAI, Claude) sends
the same instruction and produces comparable output.
"""
from __future__ import annotations

from app.core.entities import ProductInput

SYSTEM_INSTRUCTION = (
    "You are an expert short-form (TikTok/Reels) UGC ad scriptwriter. "
    "You write punchy, authentic, first-person ad scripts that sound like a "
    "real person talking to camera, not a corporate ad."
)


def build_script_prompt(product: ProductInput) -> str:
    """Return the user-facing prompt describing the exact deliverable."""
    benefits = "\n".join(f"- {b}" for b in product.benefits) or "- (none provided)"
    return f"""Write a TikTok ad script for the following product.

PRODUCT NAME: {product.name}
DESCRIPTION: {product.description}
BENEFITS:
{benefits}

STRICT REQUIREMENTS:
- UGC style, spoken first person, casual and authentic.
- Length when read aloud: 10 to 20 seconds.
- MAXIMUM 50 words total. This is a hard limit.
- Must contain, in order: a scroll-stopping HOOK, the PROBLEM, the SOLUTION
  (the product), and a clear CALL TO ACTION.
- Output ONLY the spoken script text. No scene directions, no labels, no
  markdown, no quotation marks, no emojis.
"""


MAX_WORDS = 50


def clean_script(text: str) -> str:
    """Normalise model output and enforce the hard 50-word ceiling.

    Models occasionally wrap output in quotes, add a ``Script:`` prefix or run
    slightly long. We strip the noise and truncate to ``MAX_WORDS`` so the
    contract ("<=50 words") is guaranteed regardless of provider behaviour.
    """
    cleaned = text.strip().strip('"').strip("'").strip()
    for prefix in ("script:", "ad script:", "voiceover:"):
        if cleaned.lower().startswith(prefix):
            cleaned = cleaned[len(prefix):].strip()
    words = cleaned.split()
    if len(words) > MAX_WORDS:
        cleaned = " ".join(words[:MAX_WORDS])
    return cleaned
