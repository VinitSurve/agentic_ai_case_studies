"""
PolicyLens (Case Study 2) – Embedding Engine & CPU Model Runtime

Provides CPU-compatible local embedding generation using SentenceTransformers:
- Loads sentence-transformers/all-MiniLM-L6-v2 on demand.
- Supports batch encoding with L2 normalization.
- Includes a lightweight MockEmbeddingEngine for fast, zero-dependency unit tests.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Sequence

from CS2_PolicyLens.src.config import config

logger = logging.getLogger("PolicyLens.Embeddings")


class EmbeddingEngine:
    """
    Production embedding engine backed by local SentenceTransformers on CPU.
    """

    def __init__(
        self,
        model_name: str | None = None,
        device: str | None = None,
        batch_size: int = 32,
    ) -> None:
        self.model_name = model_name or config.TOKENIZER_MODEL
        self.device = device or config.device
        self.batch_size = batch_size
        self._model = None

    @property
    def model(self):
        if self._model is None:
            logger.info("Loading embedding model %s on %s...", self.model_name, self.device)
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.model_name, device=self.device)
        return self._model

    def encode(self, texts: Sequence[str]) -> list[list[float]]:
        """
        Generates normalized embedding vectors for a batch of strings.
        Returns a list of 384-dimensional float lists.
        """
        if not texts:
            return []

        embeddings = self.model.encode(
            list(texts),
            batch_size=self.batch_size,
            show_progress_bar=False,
            normalize_embeddings=True,
        )
        return embeddings.tolist()


class MockEmbeddingEngine:
    """
    Deterministic mock embedding engine for tests that does not load PyTorch weights
    or access the internet. Generates deterministic 384-dimensional unit vectors.
    """

    def __init__(self, dimension: int = 384) -> None:
        self.dimension = dimension

    def encode(self, texts: Sequence[str]) -> list[list[float]]:
        results: list[list[float]] = []
        for text in texts:
            # Deterministic pseudo-random vector derived from MD5/SHA256 of text
            h = hashlib.sha256(text.encode("utf-8")).digest()
            raw = [(h[i % len(h)] / 255.0) - 0.5 for i in range(self.dimension)]
            # Normalize to unit length
            norm = sum(x * x for x in raw) ** 0.5 or 1.0
            results.append([round(x / norm, 6) for x in raw])
        return results

