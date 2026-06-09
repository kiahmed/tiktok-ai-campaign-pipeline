"""Creative job orchestrator — drives the agent state machine.

Dispatches the right agent for a job's current status, persists every
transition, and owns the cross-cutting control flow that is NOT any single
agent's job:

  * REJECTED  -> regenerate (reset to DRAFT, attempt++) until max_attempts,
                 then DISCARDED.
  * APPROVED  -> post via the Ad agent, unless the job opted out of posting.
  * any agent raising -> job marked FAILED with the error recorded.

State machine:
  DRAFT -> SCRIPTED -> VIDEO_READY -> (APPROVED|REJECTED)
  APPROVED -> LIVE        REJECTED -> DRAFT (retry) | DISCARDED
"""
from __future__ import annotations

import logging

from app.agents import (
    CreativeStrategistAgent,
    QualityReviewAgent,
    TikTokAdAgent,
    VideoProductionAgent,
)
from app.database.models import JobStatus
from app.repositories import CreativeJobRepository

logger = logging.getLogger("orchestrator")

# Once a job reaches one of these it is done (for the run loop).
TERMINAL = {JobStatus.LIVE, JobStatus.DISCARDED, JobStatus.FAILED}


class CreativeJobOrchestrator:
    def __init__(
        self,
        *,
        job_repo: CreativeJobRepository,
        strategist: CreativeStrategistAgent,
        video_agent: VideoProductionAgent,
        qc_agent: QualityReviewAgent,
        ad_agent: TikTokAdAgent,
    ) -> None:
        self._jobs = job_repo
        self._strategist = strategist
        self._video = video_agent
        self._qc = qc_agent
        self._ad = ad_agent

    def process(self, job_id: int, *, max_steps: int = 20) -> "object":
        """Run a job forward until it reaches a terminal/blocked state."""
        job = self._jobs.get(job_id)
        if job is None:
            raise ValueError(f"job {job_id} not found")

        for _ in range(max_steps):
            agent = self._agent_for(job.status)
            if agent is None:
                break  # terminal, or APPROVED-but-not-posting => blocked

            try:
                result = agent.run(job)
            except Exception as exc:  # any agent failure -> FAILED, never crash
                logger.exception("Agent %s failed on job %s", agent.name, job.id)
                job = self._jobs.update(job.id, status=JobStatus.FAILED, last_error=str(exc))
                break

            job = self._apply(job, result)
            if job.status in TERMINAL or self._is_blocked(job):
                break

        return job

    # ---- internals ----
    def _agent_for(self, status: JobStatus):
        if status == JobStatus.DRAFT:
            return self._strategist
        if status == JobStatus.SCRIPTED:
            return self._video
        if status == JobStatus.VIDEO_READY:
            return self._qc
        if status == JobStatus.APPROVED:
            return self._ad
        return None

    @staticmethod
    def _is_blocked(job) -> bool:
        # APPROVED with posting disabled is a deliberate stop point.
        return job.status == JobStatus.APPROVED and not job.post_to_platform

    def _apply(self, job, result):
        """Persist the agent result and compute the next state."""
        if result.next_status == JobStatus.REJECTED:
            attempt = job.attempt + 1
            codes = result.data.get("codes", [])
            if attempt >= job.max_attempts:
                logger.info("Job %s DISCARDED after %d attempts", job.id, attempt)
                return self._jobs.update(
                    job.id,
                    status=JobStatus.DISCARDED,
                    attempt=attempt,
                    discard_reason="; ".join(codes) or "rejected repeatedly",
                )
            logger.info("Job %s rejected (attempt %d) -> regenerating", job.id, attempt)
            # Reset to DRAFT so the Strategist produces a fresh candidate.
            return self._jobs.update(
                job.id,
                status=JobStatus.DRAFT,
                attempt=attempt,
                script_id=None,
                video_id=None,
            )

        return self._jobs.update(job.id, status=result.next_status, **result.updates)
