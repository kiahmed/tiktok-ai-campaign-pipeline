"""Persistence for dry-run preview history."""
from __future__ import annotations

import json

from sqlalchemy import select

from app.database.models import PreviewRun
from app.repositories.base import BaseRepository


def _dumps(value) -> str | None:
    if value is None:
        return None
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return json.dumps({"unserializable": str(value)})


class PreviewRunRepository(BaseRepository):
    def create(
        self,
        *,
        product_id: int | None,
        product_name: str,
        provider: str,
        script: dict | None,
        scene_prompt: str | None,
        payload: dict | None,
        calls: list | None,
    ) -> PreviewRun:
        with self._unit_of_work() as session:
            row = PreviewRun(
                product_id=product_id or None,
                product_name=product_name or "",
                provider=provider or "",
                script_json=_dumps(script),
                scene_prompt=scene_prompt,
                payload_json=_dumps(payload),
                calls_json=_dumps(calls),
            )
            session.add(row)
            session.flush()
            session.refresh(row)
            session.expunge(row)
            return row

    def list_recent(self, limit: int = 50) -> list[PreviewRun]:
        with self._unit_of_work() as session:
            rows = session.scalars(
                select(PreviewRun).order_by(PreviewRun.id.desc()).limit(limit)
            ).all()
            for row in rows:
                session.expunge(row)
            return list(rows)

    def get(self, pk: int) -> PreviewRun | None:
        with self._unit_of_work() as session:
            row = session.get(PreviewRun, pk)
            if row is not None:
                session.expunge(row)
            return row
