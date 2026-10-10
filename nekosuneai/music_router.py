"""Music Assistant-first music transport with local YouTube fallback."""
from __future__ import annotations

import logging
import os
from typing import Any, Callable

from .music import MusicController
from .music_assistant_client import MusicAssistantClient

LOG = logging.getLogger(__name__)


class RoutedMusicController:
    def __init__(self, notify: Callable[[str], None] | None = None) -> None:
        self.local = MusicController(notify=notify)
        self.client = MusicAssistantClient(
            base_url=os.getenv("MUSIC_ASSISTANT_URL", ""),
            token=os.getenv("MUSIC_ASSISTANT_TOKEN", ""),
            player_id=os.getenv("MUSIC_ASSISTANT_PLAYER_ID", ""),
            verify_tls=os.getenv("MUSIC_ASSISTANT_VERIFY_TLS", "true").lower() not in ("0", "false", "no"),
        )
        self.fallback = os.getenv("MUSIC_YOUTUBE_FALLBACK", "true").lower() not in ("0", "false", "no")
        self.active = ""

    def play(self, queries: list[str], replace: bool = True) -> dict[str, Any]:
        cleaned = [str(x).strip() for x in queries if str(x).strip()]
        if not cleaned:
            raise ValueError("music.play requires a query")
        if self.client.playable:
            try:
                if replace:
                    self.local.stop()
                # Music Assistant maintains the selected player's queue.
                results = []
                for query in cleaned:
                    results.append(self.client.play_query(query))
                self.active = "music_assistant"
                return {"ok": True, "playing": True, "source": "music_assistant",
                        "title": results[-1].get("name", cleaned[-1]), "queued": max(0, len(results)-1)}
            except Exception as exc:
                LOG.warning("Music Assistant could not play request; trying YouTube fallback: %s", exc)
                if not self.fallback:
                    raise
        elif not self.fallback:
            raise RuntimeError("Music Assistant URL, token, or player ID not configured")
        if replace and self.active == "music_assistant" and self.client.playable:
            try:
                self.client.queue_command("stop")
            except Exception:
                LOG.warning("Could not stop Music Assistant before fallback", exc_info=True)
                raise RuntimeError("Cannot safely start YouTube while Music Assistant may still be playing")
        result = self.local.play(cleaned, replace=replace)
        self.active = "youtube"
        return {**result, "source": "youtube", "fallback": True}

    def _command(self, action: str, local_action: str) -> dict[str, Any]:
        if self.active == "music_assistant":
            self.client.queue_command(action)
            if action == "stop":
                self.active = ""
            return {"ok": True, "source": "music_assistant", "action": action}
        result = getattr(self.local, local_action)()
        if action == "stop":
            self.active = ""
        return result

    def stop(self) -> dict[str, Any]:
        if self.active == "music_assistant":
            self.local.stop()
        return self._command("stop", "stop")

    def pause(self) -> dict[str, Any]:
        return self._command("pause", "pause")

    def resume(self) -> dict[str, Any]:
        return self._command("resume", "resume")

    def skip(self) -> dict[str, Any]:
        return self._command("next", "skip")

    def previous(self) -> dict[str, Any]:
        return self._command("previous", "previous")

    def set_volume(self, percent: int) -> dict[str, Any]:
        if self.active == "music_assistant":
            self.client.command("players/cmd/volume_set", {
                "player_id": self.client.player_id, "volume_level": max(0, min(100, int(percent)))
            })
            return {"ok": True, "source": "music_assistant", "volume": percent}
        return self.local.set_volume(percent)

    def is_playing(self) -> bool:
        if self.active == "music_assistant":
            try:
                q = self.client.status().get("queue") or {}
                return str(q.get("state", "")).lower() in ("playing", "play")
            except Exception:
                return False
        return self.local.is_playing()

    def status(self) -> dict[str, Any]:
        if self.active == "music_assistant":
            info = self.client.status()
            queue = info.get("queue") or {}
            item = queue.get("current_item") or {}
            media = item.get("media_item") or {}
            return {"source": "music_assistant", "playing": self.is_playing(),
                    "title": media.get("name") or item.get("name") or "",
                    "paused": str(queue.get("state", "")).lower() == "paused",
                    "queue": [], "queued": queue.get("items", 0), "volume": 100,
                    "error": info.get("error", "")}
        return {**self.local.status(), "source": self.active or "youtube"}
