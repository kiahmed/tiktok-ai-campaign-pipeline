"""Creative strategy: controlled taxonomy, angle selection, novelty, prompting."""
from app.services.strategy.taxonomy import ANGLES, HOOK_TYPES
from app.services.strategy.angle_selector import AngleSelector, ScriptBrief
from app.services.strategy.novelty import (
    NoveltyChecker,
    LexicalNovelty,
    EmbeddingNovelty,
    max_similarity,
    is_novel,
)

__all__ = [
    "ANGLES",
    "HOOK_TYPES",
    "AngleSelector",
    "ScriptBrief",
    "NoveltyChecker",
    "LexicalNovelty",
    "EmbeddingNovelty",
    "max_similarity",
    "is_novel",
]
