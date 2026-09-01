"""Bounded Twitch chat prioritisation with strict public/private separation."""
from __future__ import annotations

import hashlib
import re
import threading
import time
from collections import deque
from typing import Any, Callable


ReplyGenerator = Callable[[str, str], str]


class TwitchChatManager:
    def __init__(
        self,
        reply_generator: ReplyGenerator,
        companion_name: str = "NekoSuneAI",
        *,
        cooldown_seconds: int = 12,
        max_queue: int = 100,
        now_fn: Callable[[], float] = time.time,
    ) -> None:
        self.reply_generator = reply_generator
        self.companion_name = companion_name
        self.cooldown = max(3, int(cooldown_seconds))
        self.max_queue = max(20, min(int(max_queue), 500))
        self.now = now_fn
        self._seen: deque[str] = deque(maxlen=1000)
        self._seen_set: set[str] = set()
        self._last_user: dict[str, float] = {}
        self._recent_text: deque[str] = deque(maxlen=30)
        self._lock = threading.RLock()

    def _remember_id(self, message_id: str) -> bool:
        if message_id in self._seen_set:
            return False
        if len(self._seen) == self._seen.maxlen:
            self._seen_set.discard(self._seen[0])
        self._seen.append(message_id)
        self._seen_set.add(message_id)
        return True

    def ingest(self, messages: list[dict[str, Any]]) -> list[dict[str, str]]:
        """Return safe public replies; never return a game/OBS/node command."""
        replies: list[dict[str, str]] = []
        with self._lock:
            for row in messages[:self.max_queue]:
                user = re.sub(r"[^a-zA-Z0-9_]", "", str(row.get("user") or "viewer"))[:25]
                text = " ".join(str(row.get("text") or "").split())[:500]
                if not text:
                    continue
                message_id = str(row.get("id") or hashlib.sha256(f"{user}:{text}:{row.get('epoch')}".encode()).hexdigest()[:16])
                if not self._remember_id(message_id):
                    continue
                lowered = text.casefold()
                # Viewer commands are a tiny, local allowlist and produce only
                # chat text. Public chat can never invoke assistant tools.
                if lowered in {"!hello", "!neko"}:
                    replies.append({"reply_to": user, "text": f"@{user} hello!"})
                    continue
                if lowered.startswith("!"):
                    continue
                mentioned = self.companion_name.casefold() in lowered or "@nekosuneai" in lowered
                question = text.endswith("?")
                if not (mentioned or question or bool(row.get("highlighted"))):
                    continue
                now = self.now()
                if now - self._last_user.get(user.casefold(), 0) < self.cooldown:
                    continue
                normalized = re.sub(r"\W+", " ", lowered).strip()
                if normalized in self._recent_text:
                    continue
                self._last_user[user.casefold()] = now
                self._recent_text.append(normalized)
                try:
                    answer = " ".join(self.reply_generator(user, text).split())[:450]
                except Exception:
                    continue
                if answer:
                    replies.append({"reply_to": user, "text": f"@{user} {answer}"})
                # One generated reply per heartbeat keeps public chat from
                # monopolising the Pi's local model during gameplay.
                if len(replies) >= 1:
                    break
        return replies
