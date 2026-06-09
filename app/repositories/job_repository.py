from __future__ import annotations

from sqlalchemy import select

from app.database.models import CreativeJob, JobStatus
from app.repositories.base import BaseRepository

# Statuses that the orchestrator should keep processing.
NON_TERMINAL = (
    JobStatus.DRAFT,
    JobStatus.SCRIPTED,
    JobStatus.VIDEO_READY,
    JobStatus.APPROVED,
)


class CreativeJobRepository(BaseRepository):
    def create(
        self,
        *,
        product_id: int,
        prepared_script: str | None = None,
        landing_page_url: str | None = None,
        post_to_platform: bool = True,
        max_attempts: int = 3,
    ) -> CreativeJob:
        with self._unit_of_work() as session:
            job = CreativeJob(
                product_id=product_id,
                status=JobStatus.DRAFT,
                prepared_script=prepared_script,
                landing_page_url=landing_page_url,
                post_to_platform=post_to_platform,
                max_attempts=max_attempts,
            )
            session.add(job)
            session.flush()
            session.refresh(job)
            session.expunge(job)
            return job

    def get(self, job_id: int) -> CreativeJob | None:
        with self._unit_of_work() as session:
            job = session.get(CreativeJob, job_id)
            if job is not None:
                session.expunge(job)
            return job

    def update(self, job_id: int, **fields) -> CreativeJob | None:
        """Patch arbitrary columns (status, script_id, attempt, last_error, ...)."""
        with self._unit_of_work() as session:
            job = session.get(CreativeJob, job_id)
            if job is None:
                return None
            for key, value in fields.items():
                setattr(job, key, value)
            session.flush()
            session.refresh(job)
            session.expunge(job)
            return job

    def list_all(self) -> list[CreativeJob]:
        with self._unit_of_work() as session:
            rows = list(
                session.scalars(
                    select(CreativeJob).order_by(CreativeJob.created_at.desc())
                ).all()
            )
            for r in rows:
                session.expunge(r)
            return rows

    def list_processable(self) -> list[CreativeJob]:
        """Jobs the orchestrator tick should advance (non-terminal states)."""
        with self._unit_of_work() as session:
            rows = list(
                session.scalars(
                    select(CreativeJob)
                    .where(CreativeJob.status.in_(NON_TERMINAL))
                    .order_by(CreativeJob.created_at.asc())
                ).all()
            )
            for r in rows:
                session.expunge(r)
            return rows
