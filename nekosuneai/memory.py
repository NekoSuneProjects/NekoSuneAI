"""Persistent retrieval-augmented memory.

Lets the assistant accumulate long-term recollections without any fine-tuning.
Interactions are written to the store, semantically similar entries are pulled
back and injected into the prompt as extra system context, and user feedback
reinforces the useful ones or prunes the rest.

Embedding is pluggable. The default is a small local sentence-transformers
model that stays on the CPU so the GPU is left to the LLM; an OpenAI-compatible
``/embeddings`` route or an Ollama endpoint can be used instead. When no
embedder works at all the store falls back to recency-ordered recall, so the
feature degrades instead of failing.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

import numpy as np
import requests

from . import database
from .config import Config

_DEFAULT_OLLAMA_ROOT = "http://127.0.0.1:11434"

# Reinforcement nudges similarity slightly; it never outranks semantic match.
_SCORE_BIAS_PER_POINT = 0.02

_PRUNE_MIN_SCORE = -2.0
_PRUNE_KEEP_RECENT = 200

_RECENT_FIELDS = ("id", "source", "speaker", "content", "score", "created_at")


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _vec_to_bytes(vec: np.ndarray) -> bytes:
    return np.asarray(vec, dtype=np.float32).reshape(-1).tobytes()


def _bytes_to_vec(blob: bytes | None) -> np.ndarray | None:
    if not blob:
        return None
    try:
        return np.frombuffer(blob, dtype=np.float32)
    except (ValueError, TypeError):
        return None


def _l2_normalize(values: Any) -> np.ndarray:
    """Unit-length a raw embedding so dot products read as cosine similarity."""
    vec = np.asarray(values, dtype=np.float32).reshape(-1)
    norm = np.linalg.norm(vec)
    return vec / norm if norm > 0 else vec


class MemoryStore:
    """Embeds, stores, recalls, and reinforces memories per profile."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self._local_model: Any = None
        self._local_model_failed = False

    # -- embedding backends -------------------------------------------------

    def _load_local_model(self) -> Any:
        """Import and cache the sentence-transformers model, once, on first use."""
        if self._local_model is not None or self._local_model_failed:
            return self._local_model

        try:
            from sentence_transformers import SentenceTransformer

            self._local_model = SentenceTransformer(self.config.rag_embedding_model)
        except Exception as exc:  # pragma: no cover - optional dep
            print(
                "[NekoSuneAI Memory] Local embeddings unavailable "
                f"({exc}). Install with: pip install sentence-transformers"
            )
            self._local_model_failed = True
        return self._local_model

    def _embed_local(self, text: str) -> np.ndarray | None:
        model = self._load_local_model()
        if model is None:
            return None
        try:
            # normalize_embeddings keeps this consistent with the remote paths.
            return np.asarray(
                model.encode(text, normalize_embeddings=True), dtype=np.float32
            ).reshape(-1)
        except Exception:
            return None

    def _embed_openai(self, text: str) -> np.ndarray | None:
        # Same host as chat completions, different route.
        base = self.config.llm_api_url.split("/chat/completions")[0].rstrip("/")

        headers = {"Content-Type": "application/json"}
        if self.config.llm_api_key:
            headers["Authorization"] = f"Bearer {self.config.llm_api_key}"

        try:
            response = requests.post(
                base + "/embeddings",
                json={"model": self.config.rag_embedding_model, "input": text},
                headers=headers,
                timeout=self.config.request_timeout,
            )
            response.raise_for_status()
            return _l2_normalize(response.json()["data"][0]["embedding"])
        except Exception:
            return None

    def _ollama_base(self) -> str:
        url = self.config.llm_api_url or f"{_DEFAULT_OLLAMA_ROOT}/api/chat"
        if "/api/" in url:
            return url.split("/api/")[0].rstrip("/")
        return _DEFAULT_OLLAMA_ROOT

    def _embed_ollama(self, text: str) -> np.ndarray | None:
        try:
            response = requests.post(
                self._ollama_base() + "/api/embeddings",
                json={"model": self.config.rag_embedding_model, "prompt": text},
                timeout=self.config.request_timeout,
            )
            response.raise_for_status()
            embedding = response.json().get("embedding")
            return _l2_normalize(embedding) if embedding else None
        except Exception:
            return None

    def _embedder(self) -> Callable[[str], np.ndarray | None]:
        """Resolve the configured provider, defaulting to the local model."""
        providers: dict[str, Callable[[str], np.ndarray | None]] = {
            "ollama": self._embed_ollama,
            "openai": self._embed_openai,
        }
        return providers.get(self.config.rag_embedding_provider, self._embed_local)

    def embed(self, text: str) -> np.ndarray | None:
        if not self.config.rag_enabled or not text.strip():
            return None
        return self._embedder()(text)

    # -- write --------------------------------------------------------------

    def remember(
        self,
        profile_id: str,
        content: str,
        source: str = "chat",
        speaker: str = "",
    ) -> int | None:
        if not self.config.rag_enabled:
            return None

        content = content.strip()
        if not content:
            return None

        vec = self.embed(content)
        return database.insert_memory(
            profile_id=profile_id,
            source=source,
            speaker=speaker,
            content=content,
            embedding=_vec_to_bytes(vec) if vec is not None else None,
            score=0.0,
            created_at=_now_iso(),
        )

    # -- read ---------------------------------------------------------------

    def _similarity(self, query_vec: np.ndarray, row: dict[str, Any]) -> float | None:
        """Cosine similarity plus a small reinforcement bias, or None if unusable."""
        vec = _bytes_to_vec(row.get("embedding"))
        if vec is None or vec.shape != query_vec.shape:
            return None

        # Both sides are unit-length, so the dot product is the cosine.
        score = float(np.dot(query_vec, vec))
        return score + _SCORE_BIAS_PER_POINT * float(row.get("score", 0) or 0)

    def recall(self, query: str, profile_id: str, k: int | None = None) -> list[str]:
        """Return up to *k* relevant memory strings for the query."""
        if not self.config.rag_enabled:
            return []

        limit = k if k is not None else self.config.rag_top_k
        rows = database.fetch_memories_for_profile(profile_id)
        if not rows:
            return []

        query_vec = self.embed(query)
        if query_vec is None:
            # No embedder available: fall back to the newest rows (id DESC).
            return [self._format(row) for row in rows[:limit]]

        threshold = self.config.rag_min_score
        scored: list[tuple[float, dict[str, Any]]] = []
        for row in rows:
            similarity = self._similarity(query_vec, row)
            if similarity is not None and similarity >= threshold:
                scored.append((similarity, row))

        scored.sort(key=lambda item: item[0], reverse=True)
        return [self._format(row) for _score, row in scored[:limit]]

    @staticmethod
    def _format(row: dict[str, Any]) -> str:
        speaker = (row.get("speaker") or "").strip()
        content = row.get("content", "")
        return f"{speaker}: {content}" if speaker else content

    # -- reinforcement and maintenance --------------------------------------

    def reinforce(self, memory_id: int, delta: float) -> None:
        database.bump_memory_score(memory_id, delta)

    def forget(self, memory_id: int) -> None:
        database.delete_memory(memory_id)

    def wipe(self, profile_id: str) -> int:
        """Delete every stored memory for *profile_id*. Returns the count deleted."""
        return database.delete_all_memories_for_profile(profile_id)

    def list_recent(self, profile_id: str, limit: int = 30) -> list[dict[str, Any]]:
        rows = database.fetch_memories_for_profile(profile_id)
        return [
            {field: row.get(field) for field in _RECENT_FIELDS}
            for row in rows[:limit]
        ]

    def prune(self, profile_id: str) -> int:
        return database.prune_low_memories(
            profile_id,
            min_score=_PRUNE_MIN_SCORE,
            keep_recent=_PRUNE_KEEP_RECENT,
        )
