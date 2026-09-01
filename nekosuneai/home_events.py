"""Bounded local event timeline for opted-in home and safety telemetry."""
from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any


class HomeEventTimeline:
    def __init__(self, storage_path: str | Path | None = None, retention_days: int | None = None) -> None:
        self.storage_path = Path(storage_path or os.getenv("HOME_TIMELINE_FILE", "data/home_timeline.json"))
        self.retention_days = max(1, min(3650, int(retention_days or os.getenv("HOME_TIMELINE_RETENTION_DAYS", "30"))))
        self._lock = threading.RLock()
        self._events: list[dict[str, Any]] = []
        self._load()

    def _load(self) -> None:
        try:
            raw = json.loads(self.storage_path.read_text("utf-8"))
            self._events = [row for row in raw.get("events", []) if isinstance(row, dict)][-2000:]
        except Exception:
            self._events = []
        self._prune(time.time())

    def _save(self) -> None:
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.storage_path.with_suffix(self.storage_path.suffix + ".tmp")
        tmp.write_text(json.dumps({"events": self._events[-2000:]}, indent=2, ensure_ascii=False), "utf-8")
        tmp.replace(self.storage_path)

    def _prune(self, now: float) -> None:
        cutoff = now - self.retention_days * 86400
        self._events = [row for row in self._events if float(row.get("epoch", 0)) >= cutoff][-2000:]

    def record(
        self,
        category: str,
        event: str,
        summary: str,
        *,
        room: str = "",
        source: str = "",
        severity: str = "info",
        details: dict[str, Any] | None = None,
        epoch: float | None = None,
    ) -> dict[str, Any]:
        now = time.time() if epoch is None else float(epoch)
        row = {
            "id": uuid.uuid4().hex[:12], "epoch": now,
            "category": str(category)[:50], "event": str(event)[:100],
            "summary": str(summary)[:500], "room": str(room)[:80],
            "source": str(source)[:100], "severity": str(severity)[:20],
            "details": self._sanitize(dict(details or {})),
        }
        with self._lock:
            self._prune(now)
            self._events.append(row)
            self._save()
        return dict(row)

    @classmethod
    def _sanitize(cls, value: Any) -> Any:
        """Remove credential-like keys recursively before anything reaches disk."""
        if isinstance(value, dict):
            return {
                str(key): cls._sanitize(child) for key, child in value.items()
                if not any(secret in str(key).lower() for secret in (
                    "token", "password", "secret", "credential", "authorization", "api_key", "apikey",
                ))
            }
        if isinstance(value, list):
            return [cls._sanitize(child) for child in value[:100]]
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        return str(value)[:500]

    def query(
        self,
        *,
        since_epoch: float = 0,
        category: str = "",
        room: str = "",
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        wanted_category, wanted_room = category.casefold(), room.casefold()
        with self._lock:
            rows = [
                dict(row) for row in self._events
                if float(row.get("epoch", 0)) >= float(since_epoch)
                and (not wanted_category or str(row.get("category", "")).casefold() == wanted_category)
                and (not wanted_room or str(row.get("room", "")).casefold() == wanted_room)
            ]
        return rows[-max(1, min(int(limit), 200)):]

    def latest(self, event: str, room: str = "") -> dict[str, Any] | None:
        normalize = lambda value: re.sub(r"[^a-z0-9]+", " ", str(value).casefold()).strip()
        wanted, wanted_room = normalize(event), normalize(room)
        with self._lock:
            return next((
                dict(row) for row in reversed(self._events)
                if wanted in normalize(row.get("event", ""))
                and (not wanted_room or normalize(row.get("room", "")) == wanted_room)
            ), None)
