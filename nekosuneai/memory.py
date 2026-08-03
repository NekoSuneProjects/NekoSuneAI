"""NekoSuneAI - persistent RAG memory store.

Gives NekoSuneAI a long-term memory it recalls and learns from over time,
without fine-tuning. Each interaction (chat, game) can be remembered; relevant
memories are recalled by semantic similarity and injected into the prompt as
extra system context. User feedback reinforces or prunes memories.

Embeddings default to a light local model (sentence-transformers MiniLM, CPU,
~80MB) to keep VRAM free for the LLM. An OpenAI-compatible ``/embeddings``
endpoint can be used instead. If neither is available the store degrades
gracefully to recency-based recall so the feature never hard-fails.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

import numpy as np
import requests

from . import database
from .config import Config


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _vec_to_bytes(vec: np.ndarray) -> bytes:
    arr = np.asarray(vec, dtype=np.float32).reshape(-1)
    return arr.tobytes()


def _bytes_to_vec(blob: bytes | None) -> np.ndarray | None:
    if not blob:
        return None
    try:
        return np.frombuffer(blob, dtype=np.float32)
    except (ValueError, TypeError):
        return None


class MemoryStore:
    """Embeds, stores, recalls, and reinforces memories per profile."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self._local_model: Any = None
        self._local_model_failed = False

    # ── embedding ───────────────────────────────────────────────────────────

    def _embed_local(self, text: str) -> np.ndarray | None:
        if self._local_model_failed:
            return None
        if self._local_model is None:
            try:
                from sentence_transformers import SentenceTransformer

                self._local_model = SentenceTransformer(
                    self.config.rag_embedding_model
                )
            except Exception as exc:  # pragma: no cover - optional dep
                print(
                    "[NekoSuneAI Memory] Local embeddings unavailable "
                    f"({exc}). Install with: pip install sentence-transformers"
                )
                self._local_model_failed = True
                return None
        try:
            vec = self._local_model.encode(text, normalize_embeddings=True)
            return np.asarray(vec, dtype=np.float32).reshape(-1)
        except Exception:
            return None

    def _embed_openai(self, text: str) -> np.ndarray | None:
        # Reuse the LLM base URL but target the /embeddings route.
        base = self.config.llm_api_url.split("/chat/completions")[0].rstrip("/")
        url = base + "/embeddings"
        headers = {"Content-Type": "application/json"}
        if self.config.llm_api_key:
            headers["Authorization"] = f"Bearer {self.config.llm_api_key}"
        try:
            resp = requests.post(
                url,
                json={"model": self.config.rag_embedding_model, "input": text},
                headers=headers,
                timeout=self.config.request_timeout,
            )
            resp.raise_for_status()
            data = resp.json()["data"][0]["embedding"]
            vec = np.asarray(data, dtype=np.float32).reshape(-1)
            norm = np.linalg.norm(vec)
            return vec / norm if norm > 0 else vec
        except Exception:
            return None

    def _ollama_base(self) -> str:
        url = self.config.llm_api_url or "http://127.0.0.1:11434/api/chat"
        if "/api/" in url:
            return url.split("/api/")[0].rstrip("/")
        return "http://127.0.0.1:11434"

    def _embed_ollama(self, text: str) -> np.ndarray | None:
        url = self._ollama_base() + "/api/embeddings"
        try:
            resp = requests.post(
                url,
                json={"model": self.config.rag_embedding_model, "prompt": text},
                timeout=self.config.request_timeout,
            )
            resp.raise_for_status()
            vec = resp.json().get("embedding")
            if not vec:
                return None
            arr = np.asarray(vec, dtype=np.float32).reshape(-1)
            norm = np.linalg.norm(arr)
            return arr / norm if norm > 0 else arr
        except Exception:
            return None

    def embed(self, text: str) -> np.ndarray | None:
        if not self.config.rag_enabled or not text.strip():
            return None
        provider = self.config.rag_embedding_provider
        if provider == "ollama":
            return self._embed_ollama(text)
        if provider == "openai":
            return self._embed_openai(text)
        return self._embed_local(text)

    # ── write ─────────────────────────────────────────────────────────────────

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
        blob = _vec_to_bytes(vec) if vec is not None else None
        return database.insert_memory(
            profile_id=profile_id,
            source=source,
            speaker=speaker,
            content=content,
            embedding=blob,
            score=0.0,
            created_at=_now_iso(),
        )

    # ── read ─────────────────────────────────────────────────────────────────

    def recall(self, query: str, profile_id: str, k: int | None = None) -> list[str]:
        """Return up to *k* relevant memory strings for the query."""
        if not self.config.rag_enabled:
            return []
        k = k if k is not None else self.config.rag_top_k
        rows = database.fetch_memories_for_profile(profile_id)
        if not rows:
            return []

        query_vec = self.embed(query)
        if query_vec is None:
            # Graceful fallback: most recent memories (rows are id DESC).
            return [self._format(r) for r in rows[:k]]

        scored: list[tuple[float, dict[str, Any]]] = []
        for row in rows:
            vec = _bytes_to_vec(row.get("embedding"))
            if vec is None or vec.shape != query_vec.shape:
                continue
            # vectors are normalized, so dot == cosine similarity
            sim = float(np.dot(query_vec, vec))
            # gently bias by reinforcement score
            sim += 0.02 * float(row.get("score", 0) or 0)
            if sim >= self.config.rag_min_score:
                scored.append((sim, row))

        scored.sort(key=lambda item: item[0], reverse=True)
        return [self._format(row) for _sim, row in scored[:k]]

    @staticmethod
    def _format(row: dict[str, Any]) -> str:
        speaker = (row.get("speaker") or "").strip()
        content = row.get("content", "")
        if speaker:
            return f"{speaker}: {content}"
        return content

    # ── reinforcement / maintenance ───────────────────────────────────────────

    def reinforce(self, memory_id: int, delta: float) -> None:
        database.bump_memory_score(memory_id, delta)

    def forget(self, memory_id: int) -> None:
        database.delete_memory(memory_id)

    def wipe(self, profile_id: str) -> int:
        """Delete every stored memory for *profile_id*. Returns the count deleted."""
        return database.delete_all_memories_for_profile(profile_id)

    def list_recent(self, profile_id: str, limit: int = 30) -> list[dict[str, Any]]:
        rows = database.fetch_memories_for_profile(profile_id)
        out = []
        for row in rows[:limit]:
            out.append(
                {
                    "id": row.get("id"),
                    "source": row.get("source"),
                    "speaker": row.get("speaker"),
                    "content": row.get("content"),
                    "score": row.get("score"),
                    "created_at": row.get("created_at"),
                }
            )
        return out

    def prune(self, profile_id: str) -> int:
        return database.prune_low_memories(
            profile_id,
            min_score=-2.0,
            keep_recent=200,
        )
