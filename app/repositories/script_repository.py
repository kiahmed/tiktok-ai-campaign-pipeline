from __future__ import annotations

import json

from sqlalchemy import select

from app.database.models import Script
from app.repositories.base import BaseRepository


class ScriptRepository(BaseRepository):
    def get(self, pk: int) -> Script | None:
        with self._unit_of_work() as session:
            script = session.get(Script, pk)
            if script is not None:
                session.expunge(script)
            return script

    def list_for_product(self, product_id: int, limit: int = 50) -> list[Script]:
        """Recent scripts for a product (Strategist history / novelty checks)."""
        with self._unit_of_work() as session:
            stmt = (
                select(Script)
                .where(Script.product_id == product_id)
                .order_by(Script.created_at.desc())
                .limit(limit)
            )
            rows = list(session.scalars(stmt).all())
            for r in rows:
                session.expunge(r)
            return rows

    def create(
        self,
        *,
        product_id: int,
        text: str,
        provider: str,
        model: str | None,
        word_count: int,
        hook_type: str | None = None,
        angle: str | None = None,
        audience_segment: str | None = None,
        embedding: list[float] | None = None,
        visual_prompt: str | None = None,
    ) -> Script:
        with self._unit_of_work() as session:
            script = Script(
                product_id=product_id,
                text=text,
                visual_prompt=visual_prompt,
                provider=provider,
                model=model,
                word_count=word_count,
                hook_type=hook_type,
                angle=angle,
                audience_segment=audience_segment,
                embedding=json.dumps(embedding) if embedding is not None else None,
            )
            session.add(script)
            session.flush()
            session.refresh(script)
            session.expunge(script)
            return script
