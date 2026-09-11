from __future__ import annotations

import hashlib
import math
from typing import Protocol

import httpx

from autonova.config import get_settings


class EmbeddingClient(Protocol):
    dimensions: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class OpenAIEmbeddingClient:
    def __init__(self) -> None:
        settings = get_settings()
        if not settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY is required for pgvector RAG")
        self.api_key = settings.openai_api_key
        self.base_url = settings.openai_base_url.rstrip("/")
        self.model = settings.embedding_model
        self.dimensions = settings.embedding_dimensions
        self.timeout = settings.embedding_timeout_seconds

    def embed(self, texts: list[str]) -> list[list[float]]:
        response = httpx.post(
            f"{self.base_url}/embeddings",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={"model": self.model, "input": texts, "dimensions": self.dimensions},
            timeout=self.timeout,
        )
        response.raise_for_status()
        items = sorted(response.json()["data"], key=lambda item: item["index"])
        vectors = [item["embedding"] for item in items]
        if len(vectors) != len(texts) or any(len(vector) != self.dimensions for vector in vectors):
            raise ValueError("embedding response has an unexpected shape")
        return vectors


class DeterministicEmbeddingClient:
    """Offline test double; never use it to assess production retrieval quality."""

    def __init__(self, dimensions: int = 1536) -> None:
        self.dimensions = dimensions

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            vector = [0.0] * self.dimensions
            for token in text.lower().split():
                digest = hashlib.sha256(token.encode("utf-8")).digest()
                index = int.from_bytes(digest[:4], "big") % self.dimensions
                vector[index] += 1.0 if digest[4] % 2 else -1.0
            norm = math.sqrt(sum(value * value for value in vector)) or 1.0
            vectors.append([value / norm for value in vector])
        return vectors


def get_embedding_client() -> EmbeddingClient:
    settings = get_settings()
    if settings.embedding_mode == "openai":
        return OpenAIEmbeddingClient()
    if settings.embedding_mode == "mock":
        return DeterministicEmbeddingClient(settings.embedding_dimensions)
    raise ValueError("EMBEDDING_MODE must be 'openai' or 'mock'")
