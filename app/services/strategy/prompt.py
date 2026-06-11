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
    "SCRIPT_TOO_LONG": "Keep it within the word limit — count them.",
    "SCRIPT_TOO_SHORT": "Write a FULLER script — don't stop early; reach the minimum word count so it fills the video.",
    "BANNED_CLAIM": "Do NOT make exaggerated or banned claims.",
    "SCRIPT_EMPTY": "Return a complete, non-empty script.",
    "DURATION_OUT_OF_RANGE": "Keep it readable in 10-20 seconds.",
}


_VISUAL_GUIDANCE = {
    "product": (
        "The \"visual_prompt\" describes the PRODUCT in motion for an AI video "
        "model that animates the product image — e.g. the bottle rotating, "
        "droplets, ingredients, cinematic light, slow push-in. Do NOT describe "
        "people or anyone speaking."
    ),
    "talking_head": (
        "The video is ONE PERSON delivering THIS voiceover to camera. Write "
        "\"visual_prompt\" as a vivid description of that person and scene so it "
        "is COHERENT with the script: a person matching the audience segment, "
        "with a facial expression and emotion that fit the script's message and "
        "arc; close-up selfie-style vertical 9:16, face clearly visible and "
        "actively speaking to camera, natural lighting and a fitting setting. "
        "Their lips will be lip-synced to the voiceover, so they MUST look like "
        "they are talking. Describe the person, emotion and setting — NOT the "
        "spoken words themselves."
    ),
}


def build_strategy_system(profiles: Profiles, creative_mode: str = "product") -> str:
    brand = profiles.brand
    rules = profiles.rules
    cr = profiles.creative
    visual_guidance = _VISUAL_GUIDANCE.get(creative_mode, _VISUAL_GUIDANCE["product"])
    voice = brand.voice or "authentic, casual, first-person UGC"
    banned = ", ".join(brand.banned_words + rules.banned_claims) or "none"
    word_rule = (
        f"{rules.min_words}-{rules.max_words} words (write a FULL script in this "
        f"range — do NOT go under {rules.min_words} words, it must be long enough "
        "to fill the whole video)"
        if rules.min_words
        else f"<= {rules.max_words} words"
    )

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
        "You are a real TikTok creator filming a raw, authentic UGC (user-"
        "generated-content) video — NOT a polished ad. You are not a "
        "copywriter; you are a real person who actually used this product and "
        "is telling a friend about it on camera.\n"
        f"BRAND: {brand.name or 'the brand'} — voice: {voice}.\n"
        f"Brand value props: {'; '.join(brand.value_props) or 'n/a'}.\n"
        f"{creative_lines}"
        f"NEVER use these words/claims: {banned}.\n"
        "WRITE LIKE A REAL PERSON TALKING, not an advertisement:\n"
        "- Open mid-thought, as if already mid-conversation.\n"
        "- Use everyday, casual spoken language and contractions (I'm, gonna, "
        "honestly, not gonna lie, ngl). Short, choppy sentences; a little "
        "imperfect is good.\n"
        "- Ground it in a SPECIFIC real-life moment or detail (a mirror, the "
        "shower, a comment someone made) — concrete, not generic claims.\n"
        "- NO ad-speak, NO hype words, NO slogans, NO 'introducing', NO "
        "exclamation-heavy sales pitch. Sound like a genuine recommendation.\n"
        "- End with a soft, natural CTA (e.g. 'link's in my bio if you wanna "
        "try it'), never a hard 'BUY NOW'.\n"
        f"Hard rules: {word_rule}; reads in "
        f"{rules.min_seconds:.0f}-{rules.max_seconds:.0f}s; must contain a HOOK, "
        "PROBLEM, SOLUTION and CTA, in that order.\n"
        "The \"script\" is the SPOKEN voiceover (read aloud by a real-sounding "
        "person) — natural, conversational, believable. " + visual_guidance + " Keep visual_prompt "
        "concrete, vertical-friendly, under 200 characters and NOT the spoken words.\n"
        "Output ONLY a single minified JSON object with EXACTLY these keys: "
        '"hook_type", "angle", "audience_segment", "script", "visual_prompt". '
        "No markdown, no code fences, no commentary."
    )


def build_strategy_user(
    product: ProductInput,
    brief: ScriptBrief,
    *,
    profiles: Profiles | None = None,
    stronger: bool = False,
) -> str:
    seg = brief.audience_segment
    seg_name = seg.name if seg else "general"
    pains = ", ".join(seg.pains) if seg else ""
    desires = ", ".join(seg.desires) if seg else ""

    # Selling points = the product `benefits` parameter MERGED with the brand
    # value_props from profiles.json (deduplicated, request params first). This
    # is what makes the script draw on BOTH sources at once.
    brand_props = list(profiles.brand.value_props) if profiles else []
    selling_points: list[str] = []
    for sp in list(product.benefits) + brand_props:
        sp = sp.strip()
        if sp and sp.lower() not in {s.lower() for s in selling_points}:
            selling_points.append(sp)
    benefits = "; ".join(selling_points) or "n/a"

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
                "script": "<the spoken voiceover>",
                "visual_prompt": "<what the video shows>",
            }
        )
    )
    return "\n".join(lines)
