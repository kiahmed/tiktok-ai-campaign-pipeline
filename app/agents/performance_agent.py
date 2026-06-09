"""⑤ Performance Agent — measures a LIVE ad and feeds the Knowledge store.

Pulls a metrics snapshot for the job's ad and persists it (history). This is the
"Performance Agent -> Knowledge" arrow: the data it stores is what the
Strategist's performance ranking reads (fully wired in Phase 4). Ongoing
auto-pausing across all ads remains the scheduled MonitoringService's job.
"""
from __future__ import annotations

import logging

from app.agents.base import Agent, AgentResult
from app.repositories import AdRepository, MetricRepository

logger = logging.getLogger("agent.performance")


class PerformanceAgent(Agent):
    name = "performance"

    def __init__(
        self,
        *,
        ad_platform,
        ad_repo: AdRepository,
        metric_repo: MetricRepository,
    ) -> None:
        self._ads = ad_platform
        self._ad_repo = ad_repo
        self._metric_repo = metric_repo

    def run(self, job) -> AgentResult:
        if not job.ad_id:
            return AgentResult(ok=True, data={"measured": False, "reason": "no ad yet"})
        ad_row = self._ad_repo.get(job.ad_id)
        if ad_row is None or not ad_row.ad_id:
            return AgentResult(ok=True, data={"measured": False, "reason": "ad not on platform"})

        metrics = self._ads.get_ad_metrics(ad_row.ad_id).with_derived()
        self._metric_repo.add_snapshot(ad_pk=ad_row.id, metrics=metrics)
        logger.info("Measured ad_id=%s spend=%.2f roas=%.2f", ad_row.ad_id, metrics.spend, metrics.roas)
        return AgentResult(
            ok=True,
            data={"measured": True, "spend": metrics.spend, "roas": metrics.roas},
        )
