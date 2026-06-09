"""Local text embedder — runs entirely on-device, no API.

Wraps ``sentence-transformers`` (default model ``all-MiniLM-L6-v2``, 384-dim).
The heavy import and the ~100 MB model load happen lazily on first use, so the
rest of the app — and the default lexical novelty path — never pay for it.

The model downloads once to the local HuggingFace cache, then runs fully
offline. Set ``HF_HUB_OFFLINE=1`` to forbid any network after that.
"""
from __future__ import annotations

import logging

from app.core.exceptions import ConfigurationError

logger = logging.getLogger("embeddings.local")


class LocalEmbedder:
    def __init__(self, model_name: str = "all-MiniLM-L6-v2") -> None:
        self._model_name = model_name
        self._model = None  # loaded lazily

    def _ensure_model(self):
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:  # optional dependency
                raise ConfigurationError(
                    "NOVELTY_METHOD=embedding requires 'sentence-transformers'. "
                    "Install it with: pip install -r requirements-embeddings.txt"
                ) from exc
            logger.info("Loading local embedding model '%s' (first time may download)", self._model_name)
            self._model = SentenceTransformer(self._model_name)
        return self._model

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return a unit-normalised embedding vector per input text."""
        model = self._ensure_model()
        vectors = model.encode(list(texts), normalize_embeddings=True)
        return [v.tolist() for v in vectors]
