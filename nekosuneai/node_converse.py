"""Conversational turns initiated by an authenticated peripheral node.

Contract NODE-CONVERSE-01. Before this, `/api/nodes/heartbeat` + `/api/nodes/poll`
only let a node report telemetry and execute commands this backend had already
decided to send -- there was no path for a node to *start* a turn. A Pi Proxy
could hear its wake word, capture an utterance and transcribe it through
`/api/nodes/media/stt`, and then had nowhere to send the transcript, so the
owner got silence back.

This module closes that loop: transcript in, assistant reply out, plus any
node-local commands that reply implies (playing music on the node's own
speaker rather than on the backend host). It is deliberately narrower than the
dashboard chat API:

* only an already-paired node with a valid device token reaches it,
* the turn is rate limited per node and globally,
* returned commands are filtered through the same capability policy
  `enqueue()` enforces, so this cannot become a way around owner policy,
* commands come back inline rather than being queued, because a spoken reply
  that arrives a poll cycle late is not a conversation. They are audited via
  `record_event` since they never pass through `enqueue()`.

Music is the one intent handled here rather than by the shared pipeline. The
backend's own `handle_media_request` plays on the *backend host*, which is
wrong for a node turn -- the owner is talking to the Pi in their living room,
not to the VPS. So a play/stop request becomes a `music.play`/`music.stop`
command for the node, which resolves the stream locally with yt-dlp (it has a
residential IP; the backend may not) and plays it on its own speaker.
"""
from __future__ import annotations

import time
from collections import deque
from typing import Any

from .node_music import NodeMusicRouter

# A node turn is a person speaking out loud, so the ceiling only has to be
# above human conversational pace. These bounds exist to stop a wedged or
# compromised node from driving the LLM/TTS stack in a loop, not to ration a
# real conversation.
MIN_SECONDS_BETWEEN_TURNS = 1.0
MAX_TURNS_PER_MINUTE = 20
MAX_TEXT_CHARS = 800


class NodeConverseService:
    def __init__(self, api: Any, nodes: Any, node_media: Any, node_music: Any = None) -> None:
        self.api = api
        self.nodes = nodes
        self.node_media = node_media
        # Shared with the dashboard/chat path so a spoken "skip this song" and
        # a typed one mean the same thing rather than drifting apart.
        self.node_music = node_music or NodeMusicRouter(nodes.list_nodes)
        self._turns: dict[str, deque[float]] = {}

    def _check_rate(self, node_id: str) -> None:
        now = time.monotonic()
        history = self._turns.setdefault(node_id, deque(maxlen=MAX_TURNS_PER_MINUTE))
        if history and now - history[-1] < MIN_SECONDS_BETWEEN_TURNS:
            raise RuntimeError("that was too fast; wait a moment before speaking again")
        if len(history) == history.maxlen and now - history[0] < 60.0:
            raise RuntimeError("this node has made too many requests in the last minute")
        history.append(now)

    def _allowed(self, node_id: str, capability: str) -> bool:
        try:
            return self.nodes.action_policy(node_id, capability) == "allow"
        except Exception:
            return False

    def _music_commands(self, node_id: str, text: str) -> tuple[str, list[dict[str, Any]]] | None:
        """Route a music request to this node's own speaker.

        Returns (spoken reply, commands) or None when this is not a music
        request and the turn should go to the normal reply pipeline.

        The owner is talking *to this node*, so the commands go back to it
        rather than to whichever node the router would pick for a dashboard
        request -- speaking to the kitchen Pi should not start music in the
        living room.
        """
        planned = self.node_music.plan(text)
        if planned is None:
            return None
        reply, commands = planned
        blocked = [
            command["capability"] for command in commands
            if not self._allowed(node_id, command["capability"])
        ]
        if blocked:
            return (
                "I'm not allowed to control music on this device yet. Enable "
                f"{blocked[0]} for this node on the dashboard.",
                [],
            )
        return reply, commands

    def _generate_reply(self, text: str) -> str:
        """Run the shared reply pipeline with backend-host output suppressed.

        `_pipeline` normally speaks through the backend's own audio stack and
        can play media on the backend host. For a node turn both belong on the
        node instead, so they are turned off for the duration and restored
        afterwards -- otherwise asking the Pi a question makes the VPS talk to
        an empty room.
        """
        state = self.api.state
        previous_voice = getattr(state, "voice_enabled", False)
        previous_media = getattr(self.api, "media_enabled", False)
        state.voice_enabled = False
        self.api.media_enabled = False
        try:
            reply = self.api._pipeline(text, from_voice=True)
        finally:
            state.voice_enabled = previous_voice
            self.api.media_enabled = previous_media
        return str(reply or "").strip()

    def handle(self, node_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        text = str(payload.get("text", "")).strip()
        if not text:
            raise ValueError("converse requires non-empty text")
        if len(text) > MAX_TEXT_CHARS:
            raise ValueError(f"converse text must be at most {MAX_TEXT_CHARS} characters")
        self._check_rate(node_id)

        routed = self._music_commands(node_id, text)
        if routed is not None:
            reply, commands = routed
        else:
            reply = self._generate_reply(text)
            commands = []
        if not reply:
            reply = "Sorry, I didn't catch that."

        result: dict[str, Any] = {"ok": True, "reply": reply[:4000], "commands": commands}

        # The node asks for audio explicitly. It falls back to its own local
        # espeak-ng when this is absent, so a TTS failure must degrade the
        # turn to text rather than failing it outright -- the owner still gets
        # an answer, just in the fallback voice.
        if bool(payload.get("speak", True)) and self._allowed(node_id, "audio.speak"):
            try:
                spoken = self.node_media.handle("tts", {"text": reply[:1500]})
                result["audio_base64"] = spoken.get("audio_base64", "")
                result["content_type"] = spoken.get("content_type", "audio/wav")
            except Exception as exc:
                result["tts_error"] = str(exc)[:200]

        try:
            self.nodes.record_event(
                "conversation", node_id,
                text=text[:200],
                reply=reply[:200],
                commands=[item["capability"] for item in commands],
            )
        except Exception:
            # The turn already happened; losing its audit line must not turn a
            # working reply into an error for the owner.
            pass
        return result
