"""The Knowledge store — what the Creative Strategist learns from.

Aggregates the two feedback signals in the agent diagram:
  * Quality Review **rejections** (reasons + failure codes), and
  * past **scripts** (texts, hooks, angles, segments) for overuse/novelty.
Plus **performance** (CTR / ROAS) per angle and per hook, joined from the ads
those scripts produced — the input to exploit/explore angle selection.

Read-only.
"""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field

from app.repositories import MetricRepository, QcReviewRepository, ScriptRepository


@dataclass(slots=True)
class PerfStat:
    count: int = 0
    avg_ctr: float = 0.0
    avg_roas: float = 0.0
    total_spend: float = 0.0

    @property
    def score(self) -> float:
        """Ranking score: reward both engagement (CTR) and return (ROAS)."""
        return self.avg_ctr * max(self.avg_roas, 0.01)


@dataclass(slots=True)
class KnowledgeContext:
    product_id: int
    past_scripts: list[str] = field(default_factory=list)
    # Cached embedding per past script (aligned with past_scripts; None if absent).
    past_embeddings: list[list[float] | None] = field(default_factory=list)
    hook_counts: dict[str, int] = field(default_factory=dict)
    angle_counts: dict[str, int] = field(default_factory=dict)
    segment_counts: dict[str, int] = field(default_factory=dict)
    recent_rejection_reasons: list[str] = field(default_factory=list)
    recent_failure_codes: list[str] = field(default_factory=list)
    angle_perf: dict[str, PerfStat] = field(default_factory=dict)
    hook_perf: dict[str, PerfStat] = field(default_factory=dict)

    @property
    def overused_hooks(self) -> list[str]:
        return [h for h, n in self.hook_counts.items() if n >= 2 and h]

    @property
    def overused_angles(self) -> list[str]:
        return [a for a, n in self.angle_counts.items() if n >= 2 and a]


class KnowledgeService:
    def __init__(
        self,
        *,
        script_repo: ScriptRepository,
        qc_repo: QcReviewRepository,
        metric_repo: MetricRepository,
    ) -> None:
        self._scripts = script_repo
        self._qc = qc_repo
        self._metrics = metric_repo

    def context_for(self, product_id: int, *, history_limit: int = 50) -> KnowledgeContext:
        scripts = self._scripts.list_for_product(product_id, limit=history_limit)
        hooks = Counter(s.hook_type for s in scripts if s.hook_type)
        angles = Counter(s.angle for s in scripts if s.angle)
        segments = Counter(s.audience_segment for s in scripts if s.audience_segment)

        rejections = self._qc.recent_rejections(product_id, limit=10)
        reasons: list[str] = []
        codes: list[str] = []
        for r in rejections:
            if r.reasons:
                reasons.extend(r.reasons.split("\n"))
            if r.failure_codes:
                codes.extend(r.failure_codes.split(","))

        angle_perf, hook_perf = self._performance(product_id)

        return KnowledgeContext(
            product_id=product_id,
            past_scripts=[s.text for s in scripts],
            past_embeddings=[_parse_vector(s.embedding) for s in scripts],
            hook_counts=dict(hooks),
            angle_counts=dict(angles),
            segment_counts=dict(segments),
            recent_rejection_reasons=[r for r in reasons if r],
            recent_failure_codes=[c for c in dict.fromkeys(codes) if c],
            angle_perf=angle_perf,
            hook_perf=hook_perf,
        )

    def _performance(self, product_id: int) -> tuple[dict[str, PerfStat], dict[str, PerfStat]]:
        rows = self._metrics.performance_rows(product_id)
        angle_acc: dict[str, list] = {}
        hook_acc: dict[str, list] = {}
        for angle, hook, ctr, roas, spend in rows:
            if angle:
                angle_acc.setdefault(angle, []).append((ctr, roas, spend))
            if hook:
                hook_acc.setdefault(hook, []).append((ctr, roas, spend))
        return _aggregate(angle_acc), _aggregate(hook_acc)


def _parse_vector(raw: str | None) -> list[float] | None:
    if not raw:
        return None
    try:
        vec = json.loads(raw)
        return vec if isinstance(vec, list) else None
    except json.JSONDecodeError:
        return None


def _aggregate(acc: dict[str, list]) -> dict[str, PerfStat]:
    out: dict[str, PerfStat] = {}
    for key, samples in acc.items():
        n = len(samples)
        out[key] = PerfStat(
            count=n,
            avg_ctr=sum(s[0] for s in samples) / n,
            avg_roas=sum(s[1] for s in samples) / n,
            total_spend=sum(s[2] for s in samples),
        )
    return out
