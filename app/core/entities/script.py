from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class ScriptResult:
    """A generated TikTok ad script, returned by any ScriptGenerator."""

    text: str
    provider: str
    model: str | None = None
    word_count: int = 0

    def __post_init__(self) -> None:
        if not self.word_count:
            self.word_count = len(self.text.split())
