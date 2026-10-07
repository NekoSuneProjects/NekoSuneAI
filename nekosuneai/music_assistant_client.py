from __future__ import annotations

"""Small authenticated client for a self-hosted Music Assistant server.

Music Assistant remains responsible for its own provider/library search and
queue. YouTube playback on a Pi Proxy intentionally remains a separate path:
the backend sends the query/URL to the Pi and yt-dlp resolves it from the
residential connection there.
"""

import itertools
from typing import Any

import requests


class MusicAssistantError(RuntimeError):
    pass


class MusicAssistantClient:
    def __init__(
        self,
        base_url: str = "",
        token: str = "",
        player_id: str = "",
        *,
        timeout: float = 10.0,
        verify_tls: bool = True,
    ) -> None:
        self.base_url = str(base_url or "").strip().rstrip("/")
        self.token = str(token or "").strip()
        self.player_id = str(player_id or "").strip()
        self.timeout = max(2.0, float(timeout))
        self.verify_tls = bool(verify_tls)
        self.session = requests.Session()
        self._ids = itertools.count(1)
        self.last_error = ""

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.token)

    @property
    def playable(self) -> bool:
        return bool(self.configured and self.player_id)

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def command(self, command: str, args: dict[str, Any] | None = None) -> Any:
        if not self.configured:
            raise MusicAssistantError("Music Assistant URL/token are not configured")
        response = self.session.post(
            self.base_url + "/api",
            headers=self._headers(),
            json={
                "message_id": str(next(self._ids)),
                "command": str(command),
                "args": dict(args or {}),
            },
            timeout=self.timeout,
            verify=self.verify_tls,
        )
        if response.status_code in {401, 403}:
            raise MusicAssistantError("Music Assistant rejected the access token")
        try:
            payload = response.json()
        except ValueError as exc:
            raise MusicAssistantError(
                f"Music Assistant returned HTTP {response.status_code} without JSON"
            ) from exc
        if not response.ok:
            raise MusicAssistantError(
                str(payload.get("error") if isinstance(payload, dict) else payload)
                or f"Music Assistant HTTP {response.status_code}"
            )
        if isinstance(payload, dict) and payload.get("error"):
            raise MusicAssistantError(str(payload["error"]))
        self.last_error = ""
        if isinstance(payload, dict) and "result" in payload:
            return payload["result"]
        return payload

    @staticmethod
    def _candidate_items(result: Any) -> list[dict[str, Any]]:
        if not isinstance(result, dict):
            return []
        # Prefer exact playable items before album/artist containers.
        ordered = ("tracks", "radio", "playlists", "albums", "artists")
        rows: list[dict[str, Any]] = []
        for key in ordered:
            value = result.get(key)
            if isinstance(value, list):
                rows.extend(item for item in value if isinstance(item, dict))
        return rows

    def search(self, query: str, *, limit: int = 8) -> list[dict[str, Any]]:
        result = self.command(
            "music/search",
            {
                "search_query": str(query).strip(),
                "limit": max(1, min(int(limit), 25)),
                "media_types": ["track", "playlist", "radio", "album", "artist"],
            },
        )
        return self._candidate_items(result)

    def find(self, query: str) -> dict[str, Any] | None:
        items = self.search(query)
        return items[0] if items else None

    @staticmethod
    def _uri(item: dict[str, Any]) -> str:
        uri = str(item.get("uri") or "").strip()
        if uri:
            return uri
        # Older/newer MA result shapes can provide provider + item id instead.
        provider = str(
            item.get("provider")
            or item.get("provider_instance")
            or item.get("provider_instance_id")
            or ""
        ).strip()
        media_type = str(item.get("media_type") or item.get("type") or "").strip()
        item_id = str(item.get("item_id") or item.get("id") or "").strip()
        if provider and media_type and item_id:
            return f"{provider}://{media_type}/{item_id}"
        return ""

    def play_query(self, query: str, *, queue_id: str | None = None) -> dict[str, Any]:
        if not self.playable:
            raise MusicAssistantError(
                "Music Assistant player id is not configured; set MUSIC_ASSISTANT_PLAYER_ID"
            )
        item = self.find(query)
        if item is None:
            raise MusicAssistantError(f"Music Assistant found no result for {query!r}")
        uri = self._uri(item)
        if not uri:
            raise MusicAssistantError("Music Assistant search result had no playable URI")
        target = str(queue_id or self.player_id)
        self.command(
            "player_queues/play_media",
            {"queue_id": target, "media": uri},
        )
        name = str(item.get("name") or item.get("title") or query)
        artists = item.get("artists")
        artist = ""
        if isinstance(artists, list) and artists:
            first = artists[0]
            if isinstance(first, dict):
                artist = str(first.get("name") or "")
            else:
                artist = str(first)
        return {
            "ok": True,
            "name": name,
            "artist": artist,
            "uri": uri,
            "queue_id": target,
        }

    def queue_command(self, action: str) -> Any:
        if not self.playable:
            raise MusicAssistantError("Music Assistant player id is not configured")
        command = {
            "play": "player_queues/play",
            "resume": "player_queues/play",
            "pause": "player_queues/pause",
            "stop": "player_queues/stop",
            "next": "player_queues/next",
            "previous": "player_queues/previous",
        }.get(str(action).lower())
        if command is None:
            raise MusicAssistantError(f"unsupported Music Assistant queue action: {action}")
        return self.command(command, {"queue_id": self.player_id})

    def status(self) -> dict[str, Any]:
        if not self.configured:
            return {"configured": False, "playable": False}
        try:
            queues = self.command("player_queues/all", {})
            row = None
            if isinstance(queues, list):
                row = next(
                    (
                        item for item in queues
                        if isinstance(item, dict)
                        and str(item.get("queue_id") or item.get("player_id") or "") == self.player_id
                    ),
                    None,
                )
            return {
                "configured": True,
                "playable": self.playable,
                "player_id": self.player_id,
                "queue": row or {},
                "error": "",
            }
        except Exception as exc:
            self.last_error = str(exc)[:300]
            return {
                "configured": True,
                "playable": self.playable,
                "player_id": self.player_id,
                "queue": {},
                "error": self.last_error,
            }
