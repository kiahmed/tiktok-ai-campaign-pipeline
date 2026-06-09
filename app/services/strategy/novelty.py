"""Script novelty / anti-duplication checks (pluggable backends).

Two interchangeable strategies behind one :class:`NoveltyChecker` contract:

* ``LexicalNovelty`` — word 3-gram Jaccard. Zero dependencies, offline,
  instant. Catches verbatim repeats and light paraphrases, but misses
  reworded duplicates ("thinning crown" vs "receding hairline").
* ``EmbeddingNovelty`` — cosine similarity over LOCAL embeddings (no API).
  Catches semantic duplicates. Needs a local model (sentence-transformers).

Selected via ``NOVELTY_METHOD`` in config. The Strategist depends only on the
``NoveltyChecker`` interface, so swapping is a configuration change.
"""
from __future__ import annotations

import math
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass

_WORD = re.compile(r"[a-z0-9']+")


@dataclass(slots=True)
class NoveltyResult:
    """Outcome of a novelty check.

    ``candidate_vector`` is the embedding of the candidate when the embedding
    backend is used (None for lexical) — the Strategist persists it so the
    script's vector is computed once and cached, not re-embedded every run.
    """

    max_similarity: float
    candidate_vector: list[float] | None = None


# --------------------------------------------------------------------------- #
# Lexical helpers
# --------------------------------------------------------------------------- #
def _shingles(text: str, n: int = 3) -> set[tuple[str, ...]]:
    tokens = _WORD.findall(text.lower())
    if len(tokens) < n:
        return {tuple(tokens)} if tokens else set()
    return {tuple(tokens[i : i + n]) for i in range(len(tokens) - n + 1)}


def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    union = len(a | b)
    return len(a & b) / union if union else 0.0


def lexical_max_similarity(candidate: str, corpus: list[str]) -> float:
    """Highest 3-gram Jaccard similarity between candidate and any past script."""
    cand = _shingles(candidate)
    if not cand or not corpus:
        return 0.0
    return max((_jaccard(cand, _shingles(p)) for p in corpus), default=0.0)


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


# --------------------------------------------------------------------------- #
# Pluggable checkers
# --------------------------------------------------------------------------- #
class NoveltyChecker(ABC):
    name: str = "abstract"
    threshold: float = 0.5

    @abstractmethod
    def check(
        self,
        candidate: str,
        corpus_texts: list[str],
        corpus_vectors: list[list[float] | None] | None = None,
    ) -> NoveltyResult:
        """Compare ``candidate`` against the corpus.

        ``corpus_vectors`` (aligned with ``corpus_texts``) supplies cached
        embeddings so they need not be recomputed; an embedding backend embeds
        only the candidate plus any corpus entries whose vector is missing.
        """

    # Convenience wrappers used in tests / simple call sites.
    def max_similarity(self, candidate: str, corpus_texts: list[str]) -> float:
        return self.check(candidate, corpus_texts).max_similarity

    def is_novel(self, candidate: str, corpus_texts: list[str]) -> bool:
        return self.max_similarity(candidate, corpus_texts) < self.threshold


class LexicalNovelty(NoveltyChecker):
    name = "lexical"

    def __init__(self, threshold: float = 0.5) -> None:
        self.threshold = threshold

    def check(self, candidate, corpus_texts, corpus_vectors=None) -> NoveltyResult:
        return NoveltyResult(lexical_max_similarity(candidate, corpus_texts), None)


class EmbeddingNovelty(NoveltyChecker):
    """Semantic de-duplication via cosine similarity over local embeddings.

    ``embedder`` exposes ``embed(list[str]) -> list[list[float]]``. Only the
    candidate (and any corpus entry without a cached vector) is embedded, so
    history is embedded once and reused via the ``scripts.embedding`` cache.
    """

    name = "embedding"

    def __init__(self, embedder, threshold: float = 0.85) -> None:
        self._embedder = embedder
        self.threshold = threshold

    def check(self, candidate, corpus_texts, corpus_vectors=None) -> NoveltyResult:
        cand = self._embedder.embed([candidate])[0]
        if not corpus_texts:
            return NoveltyResult(0.0, cand)

        vectors: list[list[float] | None] = list(corpus_vectors or [None] * len(corpus_texts))
        # Backfill any missing corpus vectors in a single batch call.
        missing = [i for i, v in enumerate(vectors) if not v]
        if missing:
            filled = self._embedder.embed([corpus_texts[i] for i in missing])
            for j, i in enumerate(missing):
                vectors[i] = filled[j]

        sims = [_cosine(cand, v) for v in vectors if v]
        return NoveltyResult(max(sims, default=0.0), cand)


# Backwards-compatible module helpers (lexical).
def max_similarity(candidate: str, corpus: list[str]) -> float:
    return lexical_max_similarity(candidate, corpus)


def is_novel(candidate: str, corpus: list[str], *, threshold: float = 0.5) -> bool:
    return lexical_max_similarity(candidate, corpus) < threshold
