"""LLM Quality Review judge — the qualitative layer of agent ③.

The deterministic rules catch hard violations (length, missing CTA, banned
claims, missing/oversized video). This judge adds the *qualitative* assessment a
rule can't make: brand-voice fit, hook strength, clear problem/solution/CTA,
policy risk, and whether the script's length is coherent with the video.

It returns a structured verdict with the same kind of ``failure_codes`` the
rules use, so both feed the Knowledge loop identically. If the LLM is
unavailable or returns junk, ``evaluate`` returns ``None`` and the agent falls
back to the rules verdict — QC never hard-fails because the model hiccuped.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from app.core.jsonparse import extract_json
from app.services.profile_service import ProfileService

logger = logging.getLogger("service.qc_judge")

# The vocabulary the judge is asked to use (so codes are analysable, like rules).
JUDGE_CODES = [
    "WEAK_HOOK",
    "OFF_BRAND",
    "NO_CLEAR_PROBLEM",
    "NO_CLEAR_SOLUTION",
    "WEAK_CTA",
    "POLICY_RISK",
    "INCOHERENT_LENGTH",
]


@dataclass(slots=True)
class QcJudgement:
    approve: bool
    score: float
    codes: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)


class QcJudge:
    def __init__(self, *, llm, profile_service: ProfileService, enabled: bool = True) -> None:
        self._llm = llm
        self._profiles = profile_service
        self._enabled = enabled

    def evaluate(
        self, script_text: str, *, duration_seconds: float | None, aspect_ratio: str
    ) -> QcJudgement | None:
        if not self._enabled:
            return None
        try:
            raw = self._llm.complete(
                self._system_prompt(), self._user_prompt(script_text, duration_seconds, aspect_ratio)
            )
        except Exception:
            logger.warning("QC judge LLM call failed; falling back to rules", exc_info=True)
            return None

        parsed = extract_json(raw)
        if not parsed:
            logger.warning("QC judge returned unparseable output; falling back to rules")
            return None

        verdict = str(parsed.get("verdict", "")).upper()
        approve = verdict == "APPROVE"
        codes = [str(c).upper() for c in parsed.get("failure_codes", []) if c]
        reasons = [str(r) for r in parsed.get("reasons", []) if r]
        try:
            score = float(parsed.get("score", 1.0 if approve else 0.0))
        except (TypeError, ValueError):
            score = 1.0 if approve else 0.0
        # Trust the codes over the verdict label: any code => not an approval.
        if codes:
            approve = False
        return QcJudgement(approve=approve, score=score, codes=codes, reasons=reasons)

    # ---- prompts ----
    def _system_prompt(self) -> str:
        p = self._profiles.load()
        brand = p.brand
        voice = brand.voice or "authentic, casual UGC"
        banned = ", ".join(brand.banned_words + p.rules.banned_claims) or "none"
        codes = ", ".join(JUDGE_CODES)
        return (
            "You are a strict TikTok ad Quality Review reviewer.\n"
            f"BRAND: {brand.name or 'the brand'} — voice: {voice}. "
            f"Banned words/claims: {banned}.\n"
            "Judge the SCRIPT on: hook strength, brand-voice fit, a clear "
            "problem, a clear solution, a strong CTA, policy/brand-safety, and "
            "whether its spoken length fits the video duration.\n"
            f"Allowed failure_codes: [{codes}].\n"
            "Respond with ONLY minified JSON: "
            '{"verdict":"APPROVE|REJECT","score":0.0-1.0,'
            '"failure_codes":[...],"reasons":[...]}. '
            "Approve only if there are no failure codes."
        )

    @staticmethod
    def _user_prompt(script: str, duration: float | None, aspect: str) -> str:
        dur = f"{duration:.0f}s" if duration is not None else "unknown"
        return (
            f"VIDEO: aspect={aspect}, duration={dur}.\n"
            f"SCRIPT:\n\"\"\"\n{script}\n\"\"\"\n"
            "Return the JSON verdict."
        )
