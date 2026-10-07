"""Route music requests to a paired Pi Proxy node instead of the backend host.

`youtube_music.YouTubeMusicPlayer` resolves streams with yt-dlp and plays them
with ffplay *on whatever machine runs this backend*. That is wrong in two ways
for a deployment whose backend lives on a VPS:

1. YouTube's bot/cookie verification blocks datacenter IPs. A VPS gets
   "confirm you're not a robot" / "sign in to confirm your age" where a home
   Raspberry Pi's residential IP resolves the same video fine.
2. Even when resolution succeeds, the audio comes out of a speaker in a
   datacenter. The owner asking for music is at home, next to the Pi.

So when a Pi Proxy node is online and advertises music playback, music intents
become node commands and the node does the resolving and the playing. The
backend still decides *what* to play -- this is a routing layer over the same
phrasing `handle_music_request` already understands, not a second music brain.

With no such node available this returns None and the caller falls through to
the backend's own player, so a deployment without a Pi Proxy is unchanged.
"""
from __future__ import annotations

import os
import re
from typing import Any, Callable

from .music_assistant_client import MusicAssistantClient

# The node type that owns local music playback. Matches the `node_type` a Pi
# Proxy sends to /api/nodes/register.
MUSIC_NODE_TYPE = "pi-proxy"
REQUIRED_CAPABILITY = "music.play"

# Deliberately the same phrasings youtube_music.handle_music_request accepts,
# so routing to a node does not quietly understand a different set of commands
# than the backend's own player does.
_STOP = re.compile(r"\b(?:stop|turn off)\s+(?:the\s+)?music\b", re.I)
_PAUSE = re.compile(r"\bpause(?:\s+(?:the\s+)?music)?\b", re.I)
_RESUME = re.compile(r"\b(?:resume|continue)(?:\s+(?:the\s+)?music)?\b", re.I)
_SKIP = re.compile(r"\b(?:skip|next)(?:\s+(?:song|track))?\b", re.I)
_PREVIOUS = re.compile(r"\b(?:previous|last|go back)(?:\s+(?:song|track))?\b", re.I)
_STATUS = re.compile(r"\b(?:what(?:'s| is) playing|music status|now playing)\b", re.I)
_VOLUME = re.compile(r"\b(?:set\s+)?(?:music\s+)?volume\s+(?:to\s+)?(\d{1,3})\s*%?\b", re.I)
_LOUDER = re.compile(r"\b(?:turn|make)\s+(?:the\s+)?music\s+(?:up|louder)\b|\bmusic\s+(?:up|louder)\b", re.I)
_QUIETER = re.compile(r"\b(?:turn|make)\s+(?:the\s+)?music\s+(?:down|quieter|lower)\b|\bmusic\s+(?:down|quieter|lower)\b", re.I)
_PLAY = re.compile(r"\bplay\s+(.+)$", re.I)
_YOUTUBE_SUFFIX = re.compile(r"\s+(?:on|using|via)\s+(?:youtube|yt|youtube music)\s*$", re.I)
_MA_SUFFIX = re.compile(r"\s+(?:on|using|via)\s+(?:music assistant|ma)\s*$", re.I)
_BARE_PLAY = re.compile(r"^\s*(?:play|play music)\s*$", re.I)
# "play a game" / "play some game" is not a music request.
_NOT_MUSIC = re.compile(r"\bplay\s+(?:a\s+|the\s+)?game\b", re.I)

# Volume is stepped rather than absolute for "louder"/"quieter", matching the
# backend player's own +/-10. The node reports its level back in music.status.
VOLUME_STEP = 10
DEFAULT_VOLUME = 75


class NodeMusicRouter:
    def __init__(
        self,
        list_nodes: Callable[[], list[dict[str, Any]]],
        node_id: str = "",
        config_provider: Callable[[], Any] | None = None,
    ) -> None:
        self.list_nodes = list_nodes
        # An explicit node wins; otherwise the online pi-proxy node is chosen
        # automatically, which is the single-Pi case almost everyone has.
        self.node_id = str(node_id or os.getenv("MUSIC_NODE_ID", "")).strip()
        self._volume = DEFAULT_VOLUME
        self.config_provider = config_provider or (lambda: None)
        self._active_source = "youtube"

    def _music_assistant(self) -> MusicAssistantClient:
        cfg = self.config_provider()
        return MusicAssistantClient(
            getattr(cfg, "music_assistant_url", "") or "",
            getattr(cfg, "music_assistant_token", "") or "",
            getattr(cfg, "music_assistant_player_id", "") or "",
            verify_tls=bool(getattr(cfg, "music_assistant_verify_tls", True)),
        )

    def _ma_control(self, action: str) -> str | None:
        client = self._music_assistant()
        if not client.playable:
            return None
        try:
            client.queue_command(action)
            self._active_source = "music-assistant"
            return {
                "pause": "Paused Music Assistant.",
                "resume": "Resumed Music Assistant.",
                "play": "Resumed Music Assistant.",
                "stop": "Stopped Music Assistant.",
                "next": "Skipping in Music Assistant.",
                "previous": "Going back in Music Assistant.",
            }.get(action, "Music Assistant updated.")
        except Exception:
            return None
    def target_node(self) -> dict[str, Any] | None:
        """The node music should play on, or None to use the backend's player."""
        candidates = []
        for node in self.list_nodes():
            if not node.get("online"):
                continue
            capabilities = node.get("capabilities") or {}
            if REQUIRED_CAPABILITY not in capabilities:
                continue
            if self.node_id:
                if str(node.get("node_id")) == self.node_id:
                    return node
                continue
            if str(node.get("node_type", "")).lower() == MUSIC_NODE_TYPE:
                candidates.append(node)
        if not candidates:
            return None
        # Deterministic pick when several Pis are online, rather than whichever
        # the registry happened to return first. Set MUSIC_NODE_ID to choose.
        return min(candidates, key=lambda item: str(item.get("node_id", "")))

    def plan(self, text: str) -> tuple[str, list[dict[str, Any]]] | None:
        """Map a music request to (spoken reply, node commands).

        Returns None when this is not a music request at all, so the caller
        continues down its normal pipeline.
        """
        raw = str(text or "").strip()
        if not raw or _NOT_MUSIC.search(raw):
            return None

        if _STOP.search(raw):
            if self._active_source == "music-assistant":
                reply = self._ma_control("stop")
                if reply:
                    return reply, []
            self._active_source = "youtube"
            return "Stopping the music.", [{"capability": "music.stop", "arguments": {}}]
        if _PAUSE.search(raw):
            if self._active_source == "music-assistant":
                reply = self._ma_control("pause")
                if reply:
                    return reply, []
            return "Paused.", [{"capability": "music.pause", "arguments": {}}]
        if _RESUME.search(raw) or _BARE_PLAY.match(raw):
            if self._active_source == "music-assistant":
                reply = self._ma_control("resume")
                if reply:
                    return reply, []
            return "Resuming.", [{"capability": "music.resume", "arguments": {}}]
        if _SKIP.search(raw):
            if self._active_source == "music-assistant":
                reply = self._ma_control("next")
                if reply:
                    return reply, []
            return "Skipping.", [{"capability": "music.skip", "arguments": {}}]
        if _PREVIOUS.search(raw):
            if self._active_source == "music-assistant":
                reply = self._ma_control("previous")
                if reply:
                    return reply, []
            return "Going back a track.", [{"capability": "music.skip", "arguments": {"previous": True}}]
        if _STATUS.search(raw):
            # Read-only: answered from the node's heartbeat state rather than
            # by queuing a command and waiting for a reply.
            return self._status_reply(), []

        volume = _VOLUME.search(raw)
        if volume:
            level = max(0, min(int(volume.group(1)), 100))
            self._volume = level
            return f"Volume set to {level}%.", [
                {"capability": "music.volume", "arguments": {"percent": level}},
            ]
        if _LOUDER.search(raw):
            self._volume = min(100, self._volume + VOLUME_STEP)
            return f"Volume {self._volume}%.", [
                {"capability": "music.volume", "arguments": {"percent": self._volume}},
            ]
        if _QUIETER.search(raw):
            self._volume = max(0, self._volume - VOLUME_STEP)
            return f"Volume {self._volume}%.", [
                {"capability": "music.volume", "arguments": {"percent": self._volume}},
            ]

        play = _PLAY.search(raw)
        if play:
            query = play.group(1).strip()
            if query:
                force_youtube = bool(_YOUTUBE_SUFFIX.search(query))
                force_ma = bool(_MA_SUFFIX.search(query))
                query = _YOUTUBE_SUFFIX.sub("", query)
                query = _MA_SUFFIX.sub("", query).strip()
                if not force_youtube:
                    client = self._music_assistant()
                    if client.playable:
                        try:
                            result = client.play_query(query)
                            self._active_source = "music-assistant"
                            title = str(result.get("name") or query)
                            artist = str(result.get("artist") or "")
                            suffix = f" by {artist}" if artist else ""
                            return f"Playing {title}{suffix} through Music Assistant.", []
                        except Exception:
                            if force_ma:
                                return "Music Assistant could not play that request.", []
                self._active_source = "youtube"
                return f"Playing {query} from YouTube.", [
                    {"capability": "music.play", "arguments": {"query": query[:300], "source": "youtube"}},
                ]
        return None

    def _status_reply(self) -> str:
        node = self.target_node()
        state = (node or {}).get("state") or {}
        music = state.get("music") if isinstance(state.get("music"), dict) else {}
        title = str(music.get("title") or "")
        if music.get("paused") and title:
            return f"{title} is paused."
        if title:
            queued = int(music.get("queued") or 0)
            tail = f", {queued} more queued" if queued else ""
            return f"Playing {title}{tail}."
        if state.get("music_playing"):
            return "Music is playing."
        return "Nothing is playing right now."

    def handle(self, text: str, enqueue: Callable[..., Any]) -> str | None:
        """Route a music request to the node, queuing its commands.

        Returns the reply to speak, or None when there is no node to route to
        or this was not a music request -- in both cases the caller falls back
        to the backend's own player.
        """
        planned = self.plan(text)
        if planned is None:
            return None
        reply, commands = planned
        # Music Assistant commands are executed directly by plan() and return
        # no Pi commands. They must work even when no Pi Proxy is online.
        if not commands:
            return reply
        node = self.target_node()
        if node is None:
            return None
        node_id = str(node.get("node_id"))
        for command in commands:
            try:
                enqueue(
                    node_id, command["capability"], command["arguments"],
                    confirmed=True, requested_by="assistant-music",
                )
            except PermissionError as exc:
                return (
                    f"I can't control music on {node.get('name') or node_id} yet: {exc}. "
                    "Allow that capability for this node on the dashboard."
                )
            except ValueError:
                # The node does not advertise this control (an older Pi Proxy
                # with only play/stop). Fall back rather than claiming success.
                return None
        return reply
