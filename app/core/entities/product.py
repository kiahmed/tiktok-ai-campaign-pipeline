from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class ProductInput:
    """The information a seller provides about a product to advertise."""

    name: str
    image_url: str
    description: str
    benefits: list[str] = field(default_factory=list)
