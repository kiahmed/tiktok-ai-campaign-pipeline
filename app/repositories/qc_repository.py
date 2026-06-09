from __future__ import annotations

from sqlalchemy import select

from app.database.models import QcReview, QcVerdict
from app.repositories.base import BaseRepository


class QcReviewRepository(BaseRepository):
    def add(
        self,
        *,
        job_id: int,
        product_id: int,
        script_id: int | None,
        video_id: int | None,
        verdict: QcVerdict,
        score: float,
        reasons: list[str],
        failure_codes: list[str],
        reviewer: str = "rules",
        attempt: int = 0,
    ) -> QcReview:
        with self._unit_of_work() as session:
            review = QcReview(
                job_id=job_id,
                product_id=product_id,
                script_id=script_id,
                video_id=video_id,
                verdict=verdict,
                score=score,
                reasons="\n".join(reasons),
                failure_codes=",".join(failure_codes),
                reviewer=reviewer,
                attempt=attempt,
            )
            session.add(review)
            session.flush()
            session.refresh(review)
            session.expunge(review)
            return review

    def recent_rejections(self, product_id: int, limit: int = 10) -> list[QcReview]:
        """Most recent REJECT reviews for a product — the Strategist's Knowledge."""
        with self._unit_of_work() as session:
            stmt = (
                select(QcReview)
                .where(
                    QcReview.product_id == product_id,
                    QcReview.verdict == QcVerdict.REJECT,
                )
                .order_by(QcReview.created_at.desc())
                .limit(limit)
            )
            rows = list(session.scalars(stmt).all())
            for r in rows:
                session.expunge(r)
            return rows

    def list_for_job(self, job_id: int) -> list[QcReview]:
        with self._unit_of_work() as session:
            stmt = (
                select(QcReview)
                .where(QcReview.job_id == job_id)
                .order_by(QcReview.created_at.asc())
            )
            rows = list(session.scalars(stmt).all())
            for r in rows:
                session.expunge(r)
            return rows
