"""Chooses the angle / hook / audience for the next script.

Exploit vs explore (a light multi-armed-bandit policy):
  * EXPLOIT — most of the time, pick the angle/hook with the best historical
    CTR x ROAS.
  * EXPLORE — sometimes (and always when there's no data), try an angle that
    hasn't been used yet, so the system keeps discovering winners.
Overused angles/hooks (used >= 2x recently) are excluded so output stays varied,
and the audience segment is rotated to the least-recently-used one.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from app.core.entities.profile import AudienceSegment, Profiles
from app.services.knowledge_service import KnowledgeContext
from app.services.strategy.taxonomy import ANGLES, HOOK_TYPES


@dataclass(slots=True)
class ScriptBrief:
    angle: str
    hook_type: str
    audience_segment: AudienceSegment | None
    mode: str  # "exploit" | "explore"
    avoid_angles: list[str] = field(default_factory=list)
    avoid_hooks: list[str] = field(default_factory=list)
    avoid_openings: list[str] = field(default_factory=list)
    avoid_codes: list[str] = field(default_factory=list)
    perf_note: str = ""


class AngleSelector:
    def __init__(self, *, explore_rate: float = 0.3, rng: random.Random | None = None) -> None:
        self._explore_rate = explore_rate
        self._rng = rng or random.Random()

    def choose(self, profiles: Profiles, ctx: KnowledgeContext) -> ScriptBrief:
        angle, mode = self._pick_angle(ctx)
        hook = self._pick_hook(ctx, mode)
        segment = self._pick_segment(profiles, ctx)

        perf = ctx.angle_perf.get(angle)
        perf_note = (
            f"Angle '{angle}' history: CTR {perf.avg_ctr:.2%}, ROAS {perf.avg_roas:.2f} "
            f"across {perf.count} measurement(s)."
            if perf
            else f"Angle '{angle}' has no performance history yet (exploring)."
        )
        openings = [" ".join(s.split()[:6]) for s in ctx.past_scripts[:5]]

        return ScriptBrief(
            angle=angle,
            hook_type=hook,
            audience_segment=segment,
            mode=mode,
            avoid_angles=ctx.overused_angles,
            avoid_hooks=ctx.overused_hooks,
            avoid_openings=openings,
            avoid_codes=ctx.recent_failure_codes,
            perf_note=perf_note,
        )

    # ---- internals ----
    def _pick_angle(self, ctx: KnowledgeContext) -> tuple[str, str]:
        excluded = set(ctx.overused_angles)
        available = [a for a in ANGLES if a not in excluded] or list(ANGLES)
        untried = [a for a in available if a not in ctx.angle_perf]

        want_explore = (not ctx.angle_perf) or (self._rng.random() < self._explore_rate)
        if want_explore and untried:
            return self._rng.choice(untried), "explore"

        scored = [(a, ctx.angle_perf[a].score) for a in available if a in ctx.angle_perf]
        if scored:
            best = max(scored, key=lambda x: x[1])[0]
            return best, "exploit"
        if untried:
            return self._rng.choice(untried), "explore"
        return self._rng.choice(available), "explore"

    def _pick_hook(self, ctx: KnowledgeContext, mode: str) -> str:
        excluded = set(ctx.overused_hooks)
        available = [h for h in HOOK_TYPES if h not in excluded] or list(HOOK_TYPES)
        scored = [(h, ctx.hook_perf[h].score) for h in available if h in ctx.hook_perf]
        if mode == "exploit" and scored:
            return max(scored, key=lambda x: x[1])[0]
        untried = [h for h in available if h not in ctx.hook_perf]
        return self._rng.choice(untried or available)

    def _pick_segment(self, profiles: Profiles, ctx: KnowledgeContext) -> AudienceSegment | None:
        segments = profiles.audience.segments
        if not segments:
            return None
        # Least-recently-used wins; random tie-break.
        return min(
            segments,
            key=lambda s: (ctx.segment_counts.get(s.name, 0), self._rng.random()),
        )
