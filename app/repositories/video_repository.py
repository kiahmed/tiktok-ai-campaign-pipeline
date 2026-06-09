from __future__ import annotations

from sqlalchemy import select

from app.database.models import Video
from app.repositories.base import BaseRepository


class VideoRepository(BaseRepository):
    def get(self, pk: int) -> Video | None:
        with self._unit_of_work() as session:
            video = session.get(Video, pk)
            if video is not None:
                session.expunge(video)
            return video

    def get_many(self, ids: list[int]) -> dict[int, Video]:
        """Fetch several videos at once, keyed by id (for dashboard joins)."""
        if not ids:
            return {}
        with self._unit_of_work() as session:
            rows = session.scalars(select(Video).where(Video.id.in_(ids))).all()
            result: dict[int, Video] = {}
            for row in rows:
                session.expunge(row)
                result[row.id] = row
            return result

    def create(
        self,
        *,
        product_id: int,
        script_id: int,
        provider: str,
        external_job_id: str | None,
        remote_url: str | None,
        local_path: str,
        file_name: str,
        aspect_ratio: str,
        format: str,
        duration_seconds: float | None,
    ) -> Video:
        with self._unit_of_work() as session:
            video = Video(
                product_id=product_id,
                script_id=script_id,
                provider=provider,
                external_job_id=external_job_id,
                remote_url=remote_url,
                local_path=local_path,
                file_name=file_name,
                aspect_ratio=aspect_ratio,
                format=format,
                duration_seconds=duration_seconds,
            )
            session.add(video)
            session.flush()
            session.refresh(video)
            session.expunge(video)
            return video
