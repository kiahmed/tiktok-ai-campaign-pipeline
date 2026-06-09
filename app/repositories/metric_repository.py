from __future__ import annotations

from sqlalchemy import select

from app.core.entities import PerformanceMetrics
from app.database.models import Ad, Metric, Script, Video
from app.repositories.base import BaseRepository


class MetricRepository(BaseRepository):
    def add_snapshot(self, *, ad_pk: int, metrics: PerformanceMetrics) -> Metric:
        with self._unit_of_work() as session:
            row = Metric(
                ad_id=ad_pk,
                spend=metrics.spend,
                impressions=metrics.impressions,
                clicks=metrics.clicks,
                conversions=metrics.conversions,
                revenue=metrics.revenue,
                ctr=metrics.ctr,
                cpc=metrics.cpc,
                cpa=metrics.cpa,
                roas=metrics.roas,
            )
            session.add(row)
            session.flush()
            session.refresh(row)
            session.expunge(row)
            return row

    def latest(self, ad_pk: int) -> Metric | None:
        """Most recent metrics snapshot for an ad (None if never measured)."""
        with self._unit_of_work() as session:
            stmt = (
                select(Metric)
                .where(Metric.ad_id == ad_pk)
                .order_by(Metric.captured_at.desc())
                .limit(1)
            )
            row = session.scalars(stmt).first()
            if row is not None:
                session.expunge(row)
            return row

    def latest_for_ads(self, ad_pks: list[int]) -> dict[int, Metric]:
        """Latest snapshot per ad id, in one pass (for the dashboard overview)."""
        result: dict[int, Metric] = {}
        if not ad_pks:
            return result
        with self._unit_of_work() as session:
            stmt = (
                select(Metric)
                .where(Metric.ad_id.in_(ad_pks))
                .order_by(Metric.captured_at.desc())
            )
            for row in session.scalars(stmt).all():
                if row.ad_id not in result:  # first seen == newest (desc order)
                    session.expunge(row)
                    result[row.ad_id] = row
            return result

    def history(self, ad_pk: int) -> list[Metric]:
        with self._unit_of_work() as session:
            stmt = (
                select(Metric)
                .where(Metric.ad_id == ad_pk)
                .order_by(Metric.captured_at.asc())
            )
            rows = list(session.scalars(stmt).all())
            for row in rows:
                session.expunge(row)
            return rows

    def performance_rows(self, product_id: int) -> list[tuple[str | None, str | None, float, float, float]]:
        """(angle, hook_type, ctr, roas, spend) for every metric snapshot of a
        product's ads — the raw input for angle/hook performance ranking.

        Joins Metric -> Ad -> Video -> Script so each metric carries the
        creative strategy that produced it.
        """
        with self._unit_of_work() as session:
            stmt = (
                select(Script.angle, Script.hook_type, Metric.ctr, Metric.roas, Metric.spend)
                .join(Ad, Metric.ad_id == Ad.id)
                .join(Video, Ad.video_id == Video.id)
                .join(Script, Video.script_id == Script.id)
                .where(Script.product_id == product_id)
            )
            return [tuple(r) for r in session.execute(stmt).all()]
