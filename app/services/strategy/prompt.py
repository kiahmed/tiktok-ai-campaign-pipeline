"""Builds the Creative Strategist's system+user prompts.

The code has already chosen the angle / hook / segment and the things to avoid
(via :class:`AngleSelector` + Knowledge). This module turns that brief into an
instruction that makes the LLM *write to* it and return the exact JSON the spec
requires: ``{hook_type, angle, audience_segment, script}``.
"""
from __future__ import annotations

import json

from app.core.entities import ProductInput
from app.core.entities.profile import Profiles
from app.services.strategy.angle_selector import ScriptBrief

# Human guidance for the most common QC failure codes (the feedback loop).
_CODE_GUIDANCE = {
    "MISSING_CTA": "ALWAYS end with a clear call to action (e.g. 'tap the link').",
    "SCRIPT_TOO_LONG": "Keep it UNDER 50 words — count them.",
    "BANNED_CLAIM": "Do NOT make exaggerated or banned claims.",
    "SCRIPT_EMPTY": "Return a complete, non-empty script.",
    "DURATION_OUT_OF_RANGE": "Keep it readable in 10-20 seconds.",
}


def build_strategy_system(profiles: Profiles) -> str:
    brand = profiles.brand
    rules = profiles.rules
    cr = profiles.creative
    voice = brand.voice or "authentic, casual, first-person UGC"
    banned = ", ".join(brand.banned_words + rules.banned_claims) or "none"

    creative_lines = ""
    if cr.is_set:
        parts = []
        if cr.narrator:
            parts.append(
                f"The narrator/spokesperson is {cr.narrator.upper()} — write strictly "
                f"in a {cr.narrator} first-person voice."
            )
        if cr.format:
            parts.append(f"Required format: {cr.format}.")
        if cr.music:
            parts.append(
                f"The video carries emotional background music ({cr.music}); write to an "
                "emotional arc so the moment lands even before the CTA."
            )
        if cr.notes:
            parts.append(f"Hard-won learnings: {cr.notes}")
        creative_lines = "CREATIVE DIRECTION: " + " ".join(parts) + "\n"

    return (
        "You are a senior direct-response TikTok ad copywriter.\n"
        f"BRAND: {brand.name or 'the brand'} — voice: {voice}.\n"
        f"Brand value props: {'; '.join(brand.value_props) or 'n/a'}.\n"
        f"{creative_lines}"
        f"NEVER use these words/claims: {banned}.\n"
        f"Hard rules: <= {rules.max_words} words; reads in "
        f"{rules.min_seconds:.0f}-{rules.max_seconds:.0f}s; must contain a HOOK, "
        "PROBLEM, SOLUTION and CTA, in that order.\n"
        "Output ONLY a single minified JSON object with EXACTLY these keys: "
        '"hook_type", "angle", "audience_segment", "script". '
        "No markdown, no code fences, no commentary."
    )


def build_strategy_user(
    product: ProductInput, brief: ScriptBrief, *, stronger: bool = False
) -> str:
    seg = brief.audience_segment
    seg_name = seg.name if seg else "general"
    pains = ", ".join(seg.pains) if seg else ""
    desires = ", ".join(seg.desires) if seg else ""
    benefits = "; ".join(product.benefits) or "n/a"

    lines = [
        f"PRODUCT: {product.name}",
        f"DESCRIPTION: {product.description}",
        f"BENEFITS: {benefits}",
        "",
        "WRITE THIS CREATIVE:",
        f"- angle: {brief.angle}",
        f"- hook_type: {brief.hook_type}",
        f"- audience_segment: {seg_name}",
    ]
    if pains:
        lines.append(f"- their pains: {pains}")
    if desires:
        lines.append(f"- their desires: {desires}")
    lines.append(f"- strategy note: {brief.perf_note}")

    if brief.avoid_angles or brief.avoid_hooks:
        lines.append(
            f"AVOID overused angles {brief.avoid_angles} and hooks {brief.avoid_hooks}."
        )
    if brief.avoid_openings:
        lines.append(
            "Do NOT open similarly to these past scripts: "
            + " | ".join(f'"{o}..."' for o in brief.avoid_openings)
        )
    guidance = [_CODE_GUIDANCE[c] for c in brief.avoid_codes if c in _CODE_GUIDANCE]
    if guidance:
        lines.append("Lessons from past rejections: " + " ".join(guidance))
    if stronger:
        lines.append(
            "IMPORTANT: your previous attempt was too similar to an existing "
            "script. Use a clearly DIFFERENT opening line, structure and wording."
        )

    lines.append(
        "Echo the chosen hook_type, angle and audience_segment back in the JSON. "
        'Return JSON only, e.g. '
        + json.dumps(
            {
                "hook_type": brief.hook_type,
                "angle": brief.angle,
                "audience_segment": seg_name,
                "script": "<the spoken script>",
            }
        )
    )
    return "\n".join(lines)
