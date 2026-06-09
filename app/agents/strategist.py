"""① Creative Strategist Agent — produces a script candidate.

Delegates the intelligence (analyse history -> choose angle/hook via
exploit-explore -> generate -> novelty check -> structured JSON) to
:class:`ScriptStrategist`, then persists the script with its strategy metadata
(hook_type / angle / audience_segment) so the Knowledge store can learn from it.

A job may supply ``prepared_script`` to bypass the strategist entirely (testing).
"""
from __future__ import annotations

import logging

from app.agents.base import Agent, AgentResult, product_to_input
from app.core.entities import ScriptResult
from app.core.exceptions import NotFoundError
from app.database.models import CreativeJob, JobStatus
from app.repositories import ProductRepository, ScriptRepository
from app.services.script_strategist import ScriptStrategist

logger = logging.getLogger("agent.strategist")


class CreativeStrategistAgent(Agent):
    name = "creative_strategist"

    def __init__(
        self,
        *,
        strategist: ScriptStrategist,
        product_repo: ProductRepository,
        script_repo: ScriptRepository,
    ) -> None:
        self._strategist = strategist
        self._product_repo = product_repo
        self._script_repo = script_repo

    def run(self, job: CreativeJob) -> AgentResult:
        product = self._product_repo.get(job.product_id)
        if product is None:
            raise NotFoundError(f"product {job.product_id} not found")

        embedding = None
        if job.prepared_script:
            script = ScriptResult(text=job.prepared_script.strip(), provider="manual")
            hook_type = angle = segment = None
            logger.info("Using prepared script (%d words)", script.word_count)
        else:
            out = self._strategist.generate(product_to_input(product), job.product_id)
            script = ScriptResult(text=out.script, provider=out.provider, model=out.model)
            hook_type, angle, segment = out.hook_type, out.angle, out.audience_segment
            embedding = out.embedding  # cached so it isn't recomputed in future runs
            logger.info(
                "Strategist script: angle=%s hook=%s mode=%s sim=%.2f",
                angle, hook_type, out.mode, out.similarity,
            )

        row = self._script_repo.create(
            product_id=job.product_id,
            text=script.text,
            provider=script.provider,
            model=script.model,
            word_count=script.word_count,
            hook_type=hook_type,
            angle=angle,
            audience_segment=segment,
            embedding=embedding,
        )
        return AgentResult(
            ok=True,
            next_status=JobStatus.SCRIPTED,
            updates={"script_id": row.id},
            data={"script_text": script.text, "angle": angle, "hook_type": hook_type},
        )
