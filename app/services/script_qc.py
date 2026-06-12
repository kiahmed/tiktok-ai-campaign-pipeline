"""Pre-video script quality review (rules + optional LLM judge).

Runs the SCRIPT-level checks (length, CTA, banned claims, brand-voice judge)
WITHOUT a video, so a bad script can be rejected before any video-generation API
call is spent. Used by the one-shot CreativeService (/products/generate); the
agent pipeline runs the same checks in its script-QC phase.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.services.profile_service import ProfileService
from app.services.qc_judge import QcJudge


@dataclass(slots=True)
class ScriptQcResult:
    ok: bool
    codes: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    score: float = 1.0
    reviewer: str = "rules"


class ScriptQc:
    def __init__(self, *, profile_service: ProfileService, judge: QcJudge) -> None:
        self._profiles = profile_service
        self._judge = judge

    def review(self, script_text: str, word_count: int | None = None) -> ScriptQcResult:
        rules = self._profiles.load().rules
        text = (script_text or "").strip()
        wc = word_count if word_count is not None else len(text.split())
        codes: list[str] = []
        reasons: list[str] = []

        if not text:
            codes.append("SCRIPT_EMPTY")
            reasons.append("Script text is empty.")
        if wc > rules.max_words:
            codes.append("SCRIPT_TOO_LONG")
            reasons.append(f"Script is {wc} words (max {rules.max_words}).")
        elif rules.min_words and text and wc < rules.min_words:
            codes.append("SCRIPT_TOO_SHORT")
            reasons.append(f"Script is only {wc} words (min {rules.min_words}).")

        lowered = text.lower()
        if rules.cta_keywords and not any(k in lowered for k in rules.cta_keywords):
            codes.append("MISSING_CTA")
            reasons.append("No call-to-action keyword found in the script.")

        for claim in rules.banned_claims:
            if claim.lower() in lowered:
                codes.append("BANNED_CLAIM")
                reasons.append(f"Script contains a banned claim: '{claim}'.")
                break

        score = max(0.0, 1.0 - 0.25 * len(codes))
        reviewer = "rules"

        # Brand-voice / coherence LLM judge — runs on the script (no video yet).
        if "SCRIPT_EMPTY" not in codes:
            judgement = self._judge.evaluate(text, duration_seconds=None, aspect_ratio="9:16")
            if judgement is not None:
                reviewer = "rules+llm"
                score = min(score, judgement.score)
                for c in judgement.codes:
                    if c not in codes:
                        codes.append(c)
                reasons.extend(judgement.reasons)

        return ScriptQcResult(ok=not codes, codes=codes, reasons=reasons, score=score, reviewer=reviewer)
