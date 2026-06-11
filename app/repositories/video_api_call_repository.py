"""Persistence for the per-video provider API-call audit trail."""
from __future__ import annotations

import json

from sqlalchemy import select

from app.database.models import VideoApiCall
from app.repositories.base import BaseRepository


def _dumps(value) -> str | None:
    if value is None:
        return None
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return json.dumps({"unserializable": str(value)})


class VideoApiCallRepository(BaseRepository):
    def record_many(self, video_id: int, calls: list[dict]) -> int:
        """Persist a video's API-call trail. Returns the number stored."""
        if not calls:
            return 0
        with self._unit_of_work() as session:
            for seq, call in enumerate(calls):
                session.add(
                    VideoApiCall(
                        video_id=video_id,
                        seq=seq,
                        provider=str(call.get("provider", "")),
                        method=str(call.get("method", "")),
                        endpoint=str(call.get("endpoint", "")),
                        request_payload=_dumps(call.get("request")),
                        response_body=_dumps(call.get("response")),
                        status_code=call.get("status_code"),
                    )
                )
            return len(calls)

    def list_for_video(self, video_id: int) -> list[VideoApiCall]:
        with self._unit_of_work() as session:
            rows = session.scalars(
                select(VideoApiCall)
                .where(VideoApiCall.video_id == video_id)
                .order_by(VideoApiCall.seq)
            ).all()
            for row in rows:
                session.expunge(row)
            return list(rows)

    def list_recent(self, limit: int = 200) -> list[VideoApiCall]:
        """All API calls across every video, newest first (global log)."""
        with self._unit_of_work() as session:
            rows = session.scalars(
                select(VideoApiCall).order_by(VideoApiCall.id.desc()).limit(limit)
            ).all()
            for row in rows:
                session.expunge(row)
            return list(rows)
