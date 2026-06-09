from __future__ import annotations

from abc import ABC, abstractmethod

from app.core.entities import ProductInput, ScriptResult


class ScriptGenerator(ABC):
    """Generates a short UGC-style TikTok ad script for a product.

    Implementations: Gemini (default), OpenAI, Claude, ...
    """

    #: Stable provider key, e.g. "gemini". Used for logging / persistence.
    name: str = "abstract"

    @abstractmethod
    def generate(self, product: ProductInput) -> ScriptResult:
        """Produce a script (<=50 words, 10-20s, hook/problem/solution/CTA).

        Raises:
            ScriptGenerationError: if the provider cannot produce a script.
        """
        raise NotImplementedError
