"""Pulls metrics for every active ad, stores history, and auto-pauses losers.

Invoked on a schedule (hourly by default). Each active ad is processed
independently so one failing ad does not abort the whole run.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from app.core.interfaces import AdPlatform
from app.repositories import AdRepository, MetricRepository
from app.services.pause_rules import PauseRuleEngine

logger = logging.getLogger("service.monitoring")


@dataclass(slots=True)
class MonitoringRunSummary:
    evaluated: int = 0
    paused: int = 0
    errors: int = 0
    paused_ad_ids: list[str] = field(default_factory=list)


class MonitoringService:
    def __init__(
        self,
        *,
        ad_platform: AdPlatform,
        ad_repo: AdRepository,
        metric_repo: MetricRepository,
        rule_engine: PauseRuleEngine,
    ) -> None:
        self._ads = ad_platform
        self._ad_repo = ad_repo
        self._metric_repo = metric_repo
        self._rules = rule_engine

    def run_once(self) -> MonitoringRunSummary:
        summary = MonitoringRunSummary()
        active_ads = self._ad_repo.list_active()
        logger.info("Monitoring run: %d active ad(s)", len(active_ads))

        for ad in active_ads:
            try:
                metrics = self._ads.get_ad_metrics(ad.ad_id).with_derived()
                self._metric_repo.add_snapshot(ad_pk=ad.id, metrics=metrics)
                summary.evaluated += 1

                decision = self._rules.evaluate(metrics)
                if decision.should_pause:
                    logger.warning("Pausing ad %s — %s", ad.ad_id, decision.reason)
                    self._ads.pause_ad(ad.ad_id)
                    self._ad_repo.mark_paused(ad.id, decision.reason or "rule triggered")
                    summary.paused += 1
                    summary.paused_ad_ids.append(ad.ad_id)
            except Exception:
                summary.errors += 1
                logger.exception("Monitoring failed for ad_id=%s", ad.ad_id)

        logger.info(
            "Monitoring run complete: evaluated=%d paused=%d errors=%d",
            summary.evaluated,
            summary.paused,
            summary.errors,
        )
        return summary
