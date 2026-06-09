"""Creative Strategist — the brain behind agent ①.

Flow: choose a brief (angle/hook/segment via exploit-explore) -> prompt the LLM
-> parse the required JSON -> enforce <=50 words -> novelty-check against past
scripts -> retry "be different" if too similar. Returns the structured output
the spec asks for: hook_type, angle, audience_segment, script.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from app.core.entities import ProductInput
from app.core.exceptions import ScriptGenerationError
from app.core.jsonparse import extract_json
from app.providers.prompt import clean_script
from app.services.knowledge_service import KnowledgeService
from app.services.profile_service import ProfileService
from app.services.strategy.angle_selector import AngleSelector
from app.services.strategy.novelty import LexicalNovelty, NoveltyChecker
from app.services.strategy.prompt import build_strategy_system, build_strategy_user

logger = logging.getLogger("service.strategist")


@dataclass(slots=True)
class StrategyOutput:
    hook_type: str
    angle: str
    audience_segment: str | None
    script: str
    provider: str
    model: str | None
    mode: str            # exploit | explore
    similarity: float    # max similarity vs past scripts (lower = more novel)
    attempts: int
    embedding: list[float] | None = None  # cached so it isn't recomputed later


class ScriptStrategist:
    def __init__(
        self,
        *,
        llm,
        knowledge: KnowledgeService,
        profile_service: ProfileService,
        selector: AngleSelector | None = None,
        novelty: NoveltyChecker | None = None,
        max_attempts: int = 3,
    ) -> None:
        self._llm = llm
        self._knowledge = knowledge
        self._profiles = profile_service
        self._selector = selector or AngleSelector()
        self._novelty = novelty or LexicalNovelty()
        self._max_attempts = max_attempts

    def generate(self, product: ProductInput, product_id: int) -> StrategyOutput:
        profiles = self._profiles.load()
        ctx = self._knowledge.context_for(product_id)
        brief = self._selector.choose(profiles, ctx)
        logger.info(
            "Strategy: angle=%s hook=%s segment=%s mode=%s",
            brief.angle,
            brief.hook_type,
            brief.audience_segment.name if brief.audience_segment else None,
            brief.mode,
        )
        system = build_strategy_system(profiles)
        model = getattr(self._llm, "_model", None)

        best: StrategyOutput | None = None
        for attempt in range(self._max_attempts):
            user = build_strategy_user(product, brief, stronger=attempt > 0)
            raw = self._llm.complete(system, user)
            parsed = extract_json(raw)

            script = clean_script((parsed.get("script") if parsed else None) or raw)
            if not script:
                continue
            hook = (parsed.get("hook_type") if parsed else None) or brief.hook_type
            angle = (parsed.get("angle") if parsed else None) or brief.angle
            seg = (parsed.get("audience_segment") if parsed else None) or (
                brief.audience_segment.name if brief.audience_segment else None
            )
            result = self._novelty.check(script, ctx.past_scripts, ctx.past_embeddings)
            sim = result.max_similarity
            candidate = StrategyOutput(
                hook_type=str(hook),
                angle=str(angle),
                audience_segment=str(seg) if seg else None,
                script=script,
                provider=getattr(self._llm, "name", "llm"),
                model=model,
                mode=brief.mode,
                similarity=sim,
                attempts=attempt + 1,
                embedding=result.candidate_vector,
            )
            if sim < self._novelty.threshold:
                logger.info(
                    "Accepted script (%s similarity=%.2f, attempt %d)",
                    self._novelty.name, sim, attempt + 1,
                )
                return candidate
            logger.info("Too similar (%.2f); retrying with stronger differentiation", sim)
            if best is None or sim < best.similarity:
                best = candidate

        if best is None:
            raise ScriptGenerationError("strategist produced no usable script", provider="strategist")
        logger.warning("Returning least-similar script (similarity=%.2f) after retries", best.similarity)
        return best
