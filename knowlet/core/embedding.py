"""Embedding backends.

The default backend uses sentence-transformers. A `DummyBackend` is provided
for environments without torch (tests, smoke runs without API access).
"""

from __future__ import annotations

import hashlib
from typing import Protocol

import numpy as np


class EmbeddingBackend(Protocol):
    @property
    def dim(self) -> int: ...

    def embed_documents(self, texts: list[str]) -> np.ndarray: ...

    def embed_query(self, text: str) -> np.ndarray: ...


class DummyBackend:
    """Deterministic hash-based embeddings. Useful when torch is unavailable.

    Not semantically meaningful — vectors only co-locate when texts share
    sub-string patterns. Sufficient to wire up the index in tests.
    """

    def __init__(self, dim: int = 384):
        self._dim = dim

    @property
    def dim(self) -> int:
        return self._dim

    def _vec(self, text: str) -> np.ndarray:
        seed = int.from_bytes(hashlib.sha256(text.encode("utf-8")).digest()[:8], "big")
        rng = np.random.default_rng(seed)
        v = rng.standard_normal(self._dim).astype(np.float32)
        norm = float(np.linalg.norm(v))
        if norm > 0:
            v /= norm
        return v

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self._dim), dtype=np.float32)
        return np.stack([self._vec(t) for t in texts])

    def embed_query(self, text: str) -> np.ndarray:
        return self._vec(text)


class SentenceTransformersBackend:
    """sentence-transformers backend. Lazy-loads the model on first use."""

    def __init__(self, model_name: str):
        self.model_name = model_name
        self._model = None
        self._dim: int | None = None

    def _ensure(self) -> None:
        if self._model is None:
            from sentence_transformers import SentenceTransformer  # heavy import

            self._model = SentenceTransformer(self.model_name)
            getter = getattr(
                self._model, "get_embedding_dimension", None
            ) or getattr(self._model, "get_sentence_embedding_dimension")
            self._dim = int(getter())

    @property
    def dim(self) -> int:
        self._ensure()
        assert self._dim is not None
        return self._dim

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        self._ensure()
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        v = self._model.encode(  # type: ignore[union-attr]
            texts, normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=False
        )
        return v.astype(np.float32)

    def embed_query(self, text: str) -> np.ndarray:
        return self.embed_documents([text])[0]


def make_backend(backend: str, model: str, dim: int) -> EmbeddingBackend:
    if backend == "dummy":
        return DummyBackend(dim=dim)
    if backend == "sentence_transformers":
        return SentenceTransformersBackend(model_name=model)
    raise ValueError(f"unknown embedding backend: {backend}")
