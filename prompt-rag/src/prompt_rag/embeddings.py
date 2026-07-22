from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Protocol, Sequence

import httpx
import numpy as np

from .config import Settings


class Embedder(Protocol):
    @property
    def model_name(self) -> str: ...

    def embed_documents(self, texts: Sequence[str]) -> np.ndarray: ...

    def embed_query(self, text: str) -> np.ndarray: ...


class SentenceTransformerEmbedder:
    def __init__(self, model_name: str, cache_folder: str | None = None):
        if cache_folder:
            cache_path = Path(cache_folder).resolve()
            (cache_path / "hub").mkdir(parents=True, exist_ok=True)
            (cache_path / "xet").mkdir(parents=True, exist_ok=True)
            # Override stale machine-level cache paths for this process only.
            os.environ["HF_HOME"] = str(cache_path)
            os.environ["HF_HUB_CACHE"] = str(cache_path / "hub")
            os.environ["HF_XET_CACHE"] = str(cache_path / "xet")
            os.environ["HF_HUB_DISABLE_XET"] = "1"
            os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError(
                'Local embeddings require: uv pip install -e ".[local]"'
            ) from exc
        self._model_name = model_name
        self._model = SentenceTransformer(model_name, cache_folder=cache_folder)

    @property
    def model_name(self) -> str:
        return self._model_name

    def embed_documents(self, texts: Sequence[str]) -> np.ndarray:
        passages = [f"passage: {text}" for text in texts]
        return np.asarray(
            self._model.encode(passages, normalize_embeddings=True, show_progress_bar=False),
            dtype=np.float32,
        )

    def embed_query(self, text: str) -> np.ndarray:
        return np.asarray(
            self._model.encode([f"query: {text}"], normalize_embeddings=True)[0],
            dtype=np.float32,
        )


class OpenAICompatibleEmbedder:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model_name: str,
        dimensions: int = 1024,
        client: httpx.Client | None = None,
    ):
        if not base_url or not api_key or not model_name:
            raise ValueError("Embedding base URL, API key and model are required")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self._model_name = model_name
        self.dimensions = dimensions
        self._client = client or httpx.Client(timeout=120)

    @property
    def model_name(self) -> str:
        return self._model_name

    def _embed(self, texts: Sequence[str]) -> np.ndarray:
        endpoint = (
            f"{self.base_url}/embeddings"
            if self.base_url.endswith("/v1")
            else f"{self.base_url}/v1/embeddings"
        )
        payload = {
            "model": self._model_name,
            "input": list(texts),
            "dimensions": self.dimensions,
            "encoding_format": "float",
        }
        response: httpx.Response | None = None
        last_transport_error: httpx.TransportError | None = None
        for attempt in range(5):
            try:
                response = self._client.post(
                    endpoint,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json=payload,
                )
            except httpx.TransportError as exc:
                last_transport_error = exc
                if attempt == 4:
                    raise
                time.sleep(min(2**attempt, 8))
                continue
            if response.status_code not in {429, 500, 502, 503, 504}:
                response.raise_for_status()
                break
            if attempt == 4:
                response.raise_for_status()
            retry_after = response.headers.get("Retry-After")
            delay = float(retry_after) if retry_after else min(2**attempt, 8)
            time.sleep(min(delay, 30))
        if response is None:
            raise RuntimeError("Embedding API did not return a response") from last_transport_error
        ordered = sorted(response.json()["data"], key=lambda item: item["index"])
        matrix = np.asarray([item["embedding"] for item in ordered], dtype=np.float32)
        if matrix.ndim != 2 or matrix.shape[1] != self.dimensions:
            raise ValueError(
                f"Embedding API returned dimension {matrix.shape[1] if matrix.ndim == 2 else 'invalid'}; "
                f"expected {self.dimensions}"
            )
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        return matrix / np.clip(norms, 1e-12, None)

    def embed_documents(self, texts: Sequence[str]) -> np.ndarray:
        return self._embed(texts)

    def embed_query(self, text: str) -> np.ndarray:
        return self._embed([text])[0]


def build_embedder(settings: Settings) -> Embedder | None:
    provider = settings.embedding_provider.strip().lower()
    if provider in {"", "none", "disabled"}:
        return None
    if provider == "sentence-transformers":
        return SentenceTransformerEmbedder(
            settings.embedding_model, str(settings.model_cache_dir)
        )
    if provider == "openai-compatible":
        return OpenAICompatibleEmbedder(
            settings.embedding_base_url,
            settings.embedding_api_key or os.getenv("DASHSCOPE_API_KEY", ""),
            settings.embedding_model,
            settings.embedding_dimensions,
        )
    raise ValueError(f"Unknown embedding provider: {settings.embedding_provider}")
