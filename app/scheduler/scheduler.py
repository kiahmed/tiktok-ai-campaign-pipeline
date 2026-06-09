"""APScheduler wrapper that runs the monitoring job on an interval.

Uses a BackgroundScheduler so it co-exists with the FastAPI event loop. The job
is coalesced and limited to one concurrent instance so a slow run never stacks.
"""
from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.services.monitoring_service import MonitoringService

logger = logging.getLogger("scheduler")

_JOB_ID = "hourly_monitoring"


class MonitoringScheduler:
    def __init__(self, monitoring_service: MonitoringService, interval_hours: int = 1) -> None:
        self._monitoring = monitoring_service
        self._interval_hours = max(1, interval_hours)
        self._scheduler = BackgroundScheduler(timezone="UTC")

    def _job(self) -> None:
        logger.info("Scheduled monitoring job firing")
        try:
            self._monitoring.run_once()
        except Exception:  # never let a job exception kill the scheduler thread
            logger.exception("Monitoring job raised")

    def start(self) -> None:
        self._scheduler.add_job(
            self._job,
            trigger=IntervalTrigger(hours=self._interval_hours),
            id=_JOB_ID,
            replace_existing=True,
            coalesce=True,
            max_instances=1,
        )
        self._scheduler.start()
        logger.info("Monitoring scheduler started (every %dh)", self._interval_hours)

    def shutdown(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            logger.info("Monitoring scheduler stopped")

    def trigger_now(self) -> None:
        """Run the monitoring job immediately (out of band)."""
        self._scheduler.add_job(self._job, id=f"{_JOB_ID}_adhoc", replace_existing=True)
