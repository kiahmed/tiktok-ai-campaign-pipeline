"""Automatic pause-rule engine — pure business logic, no I/O.

Rules (any one triggers a pause):
    Rule 1: spend > MAX_SPEND_NO_CONV  AND  conversions == 0
    Rule 2: CTR  < MIN_CTR
    Rule 3: ROAS < MIN_ROAS

A small spend floor (``min_spend_to_evaluate``) prevents brand-new ads with a
handful of impressions from being paused before they have a fair chance.

Kept side-effect free so it is trivially unit-testable; the MonitoringService
applies the decision.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.core.entities import PerformanceMetrics


@dataclass(slots=True)
class PauseDecision:
    should_pause: bool
    reason: str | None = None


class PauseRuleEngine:
    def __init__(
        self,
        *,
        max_spend_no_conv: float = 50.0,
        min_ctr: float = 0.005,
        min_roas: float = 1.0,
        min_spend_to_evaluate: float = 5.0,
    ) -> None:
        self._max_spend_no_conv = max_spend_no_conv
        self._min_ctr = min_ctr
        self._min_roas = min_roas
        self._min_spend_to_evaluate = min_spend_to_evaluate

    def evaluate(self, m: PerformanceMetrics) -> PauseDecision:
        # Give young/low-spend ads a grace period.
        if m.spend < self._min_spend_to_evaluate:
            return PauseDecision(should_pause=False)

        # Rule 1: meaningful spend but zero conversions.
        if m.spend > self._max_spend_no_conv and m.conversions == 0:
            return PauseDecision(
                True,
                f"Rule 1: spend ${m.spend:.2f} > ${self._max_spend_no_conv:.2f} "
                f"with 0 conversions",
            )

        # Rule 2: click-through rate too low (needs impressions to be meaningful).
        if m.impressions > 0 and m.ctr < self._min_ctr:
            return PauseDecision(
                True,
                f"Rule 2: CTR {m.ctr * 100:.3f}% < {self._min_ctr * 100:.3f}%",
            )

        # Rule 3: return on ad spend below break-even (only once revenue could exist).
        if m.conversions > 0 and m.roas < self._min_roas:
            return PauseDecision(
                True,
                f"Rule 3: ROAS {m.roas:.2f} < {self._min_roas:.2f}",
            )

        return PauseDecision(should_pause=False)
