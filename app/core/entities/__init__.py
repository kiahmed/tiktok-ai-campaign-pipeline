"""Provider-agnostic domain entities (plain value objects).

These are the contracts that flow *between* layers. They are intentionally
free of any framework or vendor detail: a ``ScriptResult`` is the same object
whether it came from Gemini, OpenAI or Claude.
"""
from app.core.entities.product import ProductInput
from app.core.entities.script import ScriptResult
from app.core.entities.video import VideoResult
from app.core.entities.ad import AdCreativeResult
from app.core.entities.metric import PerformanceMetrics

__all__ = [
    "ProductInput",
    "ScriptResult",
    "VideoResult",
    "AdCreativeResult",
    "PerformanceMetrics",
]
