from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from app.core.entities import ProductInput
from app.database.models import CreativeJob, JobStatus, Product


@dataclass(slots=True)
class AgentResult:
    """What an agent reports back to the Orchestrator after running.

    ``next_status`` is the status the job should transition to on success.
    ``updates`` are columns to patch on the job (e.g. ``script_id``).
    ``data`` carries extra info (e.g. QC reasons) for the orchestrator's logic.
    """

    ok: bool = True
    next_status: JobStatus | None = None
    updates: dict = field(default_factory=dict)
    data: dict = field(default_factory=dict)
    error: str | None = None


class Agent(ABC):
    """A single-responsibility step in the creative pipeline."""

    name: str = "agent"

    @abstractmethod
    def run(self, job: CreativeJob) -> AgentResult:
        """Advance ``job`` by exactly one stage. Raise on hard failure."""
        raise NotImplementedError


def product_to_input(product: Product) -> ProductInput:
    """Convert a persisted Product row into the provider-facing entity."""
    benefits = [b for b in (product.benefits or "").split("\n") if b.strip()]
    return ProductInput(
        name=product.name,
        image_url=product.image_url,
        description=product.description,
        benefits=benefits,
    )
