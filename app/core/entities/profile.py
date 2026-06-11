from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class BrandProfile:
    """Brand voice and positioning the Strategist must stay true to."""

    name: str = ""
    voice: str = ""  # e.g. "warm, confident, friend-to-friend"
    tone_words: list[str] = field(default_factory=list)
    value_props: list[str] = field(default_factory=list)
    banned_words: list[str] = field(default_factory=list)


@dataclass(slots=True)
class AudienceSegment:
    name: str
    pains: list[str] = field(default_factory=list)
    desires: list[str] = field(default_factory=list)


@dataclass(slots=True)
class AudienceProfile:
    segments: list[AudienceSegment] = field(default_factory=list)


@dataclass(slots=True)
class CreativeRules:
    """Hard creative constraints enforced by QC and described to the Strategist."""

    min_words: int = 0   # 0 = no minimum; set to fill at least min_seconds of speech
    max_words: int = 50
    min_seconds: float = 10.0
    max_seconds: float = 20.0
    required_beats: list[str] = field(
        default_factory=lambda: ["hook", "problem", "solution", "cta"]
    )
    cta_keywords: list[str] = field(
        default_factory=lambda: [
            "tap", "shop", "buy", "try", "get", "click", "order", "link",
            "grab", "discover", "check", "swipe",
        ]
    )
    banned_claims: list[str] = field(default_factory=list)


@dataclass(slots=True)
class CreativeDirectives:
    """Tested creative formula — drives BOTH the script and the video render.

    ``narrator`` and ``music`` are video-render concerns (passed to the video
    provider if it supports them); ``format`` and ``notes`` also steer the
    script Strategist's prompt.
    """

    narrator: str = ""   # e.g. "male"
    format: str = ""     # e.g. "personal transformation story: lost confidence -> changed life"
    music: str = ""      # e.g. "cinematic, emotional, 'cool' track worth staying for"
    notes: str = ""      # freeform learnings, injected into prompts

    @property
    def is_set(self) -> bool:
        return any([self.narrator, self.format, self.music, self.notes])


@dataclass(slots=True)
class Profiles:
    brand: BrandProfile
    audience: AudienceProfile
    rules: CreativeRules
    creative: CreativeDirectives = field(default_factory=CreativeDirectives)
