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

import secrets
import threading
import time
from collections import deque
from typing import Any

from .device_turn import run_turn
from .node_music import NodeMusicRouter

# Delivered through the ordinary command queue as a second copy of the reply,
# so a turn survives losing its HTTP response. A converse request runs the
# whole pipeline -- web search, the LLM, TTS -- and on a VPS behind a reverse
# proxy that routinely outlasts the proxy's read timeout, which answers the
# node 504 and throws away a reply the backend had already produced.
REPLY_CAPABILITY = "conversation.reply"

# How long a finished turn stays remembered, so a retry that arrives after the
# original completed still gets that answer instead of running again. Longer
# than the slowest plausible turn plus a client's own retry delay.
TURN_MEMORY_SECONDS = 300.0

# A node turn is a person speaking out loud, so the ceiling only has to be
# above human conversational pace. These bounds exist to stop a wedged or
# compromised node from driving the LLM/TTS stack in a loop, not to ration a
# real conversation -- a retry of the same utterance is not a new turn and is
# handled by turn_key above, not counted here.
MIN_SECONDS_BETWEEN_TURNS = 1.0
MAX_TURNS_PER_MINUTE = 20
MAX_TEXT_CHARS = 800


class _InFlightTurn:
    """One utterance, so a retry over another transport joins it.

    A duplicate waits for the original rather than starting a second run: the
    expensive part is the LLM, and answering the same question twice is both
    wasteful and a way for the node to speak twice.
    """

    def __init__(self) -> None:
        self._done = threading.Event()
        self._result: dict[str, Any] = {}
        self._error: BaseException | None = None
        self.finished_at = 0.0

    @property
    def done(self) -> bool:
        return self._done.is_set()

    def complete(self, result: dict[str, Any] | None = None, error: BaseException | None = None) -> None:
        self._result = result or {}
        self._error = error
        self.finished_at = time.monotonic()
        self._done.set()

    def result(self) -> dict[str, Any]:
        if not self._done.wait(TURN_MEMORY_SECONDS):
            raise RuntimeError("the original attempt at this turn never finished")
        if self._error is not None:
            raise self._error
        return dict(self._result)


class NodeConverseService:
    def __init__(self, api: Any, nodes: Any, node_media: Any, node_music: Any = None) -> None:
        self.api = api
        self.nodes = nodes
        self.node_media = node_media
        # Shared with the dashboard/chat path so a spoken "skip this song" and
        # a typed one mean the same thing rather than drifting apart.
        self.node_music = node_music or NodeMusicRouter(nodes.list_nodes)
        self._turns: dict[str, deque[float]] = {}
        self._in_flight: dict[str, _InFlightTurn] = {}
        self._turn_lock = threading.Lock()

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

    def _node_name(self, node_id: str) -> str:
        try:
            for node in self.nodes.list_nodes():
                if str(node.get("node_id")) == node_id:
                    return str(node.get("name") or node_id)
        except Exception:
            pass
        return node_id

    def _generate_reply(self, text: str, speaker: str = "") -> str:
        """Run the shared reply pipeline and return what the assistant said.

        See device_turn.run_turn: the reply comes from the `_push_chat` call
        rather than `_pipeline`'s return value (which is a UI status string),
        and the backend host's own voice/media output is suppressed so
        answering the Pi does not make the VPS talk to an empty room.
        """
        return run_turn(self.api, text, from_voice=True, speaker=speaker)

    def _queue_reply(
        self, node_id: str, turn_id: str, reply: str, commands: list[dict[str, Any]],
    ) -> None:
        """Leave a copy of the reply on the node's command queue.

        The inline response is the fast path and is what normally answers the
        owner. But it has to cross whatever sits between the node and this
        backend, and a converse turn is long: on a VPS behind a reverse proxy
        the request regularly outlives the proxy's read timeout, which hands
        the node a 504 and discards a reply the backend had already finished
        computing. The queued copy is picked up by the poll the node is
        already running, seconds later, so the answer arrives either way.

        Text only, never the synthesised audio: the queue is persisted to disk
        on every write, and base64 WAVs do not belong in it. The node asks for
        TTS separately, which is a short request that survives the same proxy.

        Best-effort throughout -- the inline answer has already been produced,
        and failing to queue a backup must not turn a successful turn into an
        error.
        """
        try:
            if self.nodes.action_policy(node_id, REPLY_CAPABILITY) != "allow":
                return  # an older node that does not advertise it
            self.nodes.enqueue(
                node_id, REPLY_CAPABILITY,
                {"turn_id": turn_id, "text": reply[:4000], "commands": commands},
                confirmed=True, requested_by="assistant-converse",
            )
        except Exception:
            pass

    def handle(self, node_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        text = str(payload.get("text", "")).strip()
        if not text:
            raise ValueError("converse requires non-empty text")
        if len(text) > MAX_TEXT_CHARS:
            raise ValueError(f"converse text must be at most {MAX_TEXT_CHARS} characters")

        # A node that loses its connection mid-turn retries over its other
        # transport, carrying the same turn_key. Without this that second
        # attempt was a whole new turn: the LLM ran twice for one utterance,
        # and the rate limiter rejected the retry with "that was too fast" --
        # so the owner was told off for the node's own failover.
        turn_key = str(payload.get("turn_key") or "")
        if turn_key:
            existing = self._claim_turn(turn_key)
            if existing is not None:
                return existing.result()

        try:
            result = self._run_turn(node_id, text, payload, turn_key)
        except BaseException as exc:
            # A duplicate waiting on this turn must see the same failure rather
            # than hanging or silently getting an empty answer.
            self._finish_turn(turn_key, error=exc)
            raise
        self._finish_turn(turn_key, result=result)
        return result

    def _claim_turn(self, turn_key: str) -> "_InFlightTurn | None":
        """Claim this turn, or return the one already running or just finished."""
        now = time.monotonic()
        with self._turn_lock:
            for key, turn in list(self._in_flight.items()):
                if turn.done and now - turn.finished_at > TURN_MEMORY_SECONDS:
                    del self._in_flight[key]
            existing = self._in_flight.get(turn_key)
            if existing is not None:
                return existing
            self._in_flight[turn_key] = _InFlightTurn()
            return None

    def _finish_turn(
        self, turn_key: str, result: dict[str, Any] | None = None,
        error: BaseException | None = None,
    ) -> None:
        if not turn_key:
            return
        with self._turn_lock:
            turn = self._in_flight.get(turn_key)
        if turn is not None and not turn.done:
            turn.complete(result, error)

    def _run_turn(
        self, node_id: str, text: str, payload: dict[str, Any], turn_key: str,
    ) -> dict[str, Any]:
        self._check_rate(node_id)

        routed = self._music_commands(node_id, text)
        if routed is not None:
            reply, commands = routed
        else:
            # Attribute the turn to the device in the backend dashboard, so a
            # question asked in the living room does not read as one typed at
            # the backend.
            reply = self._generate_reply(text, speaker=self._node_name(node_id))
            commands = []
        if not reply:
            reply = "Sorry, I didn't catch that."

        # Every turn is identified so the node can recognise the queued copy
        # below as the same answer it may already have received inline, and
        # speak it once rather than twice.
        turn_id = secrets.token_hex(8)
        result: dict[str, Any] = {
            "ok": True, "turn_id": turn_id, "reply": reply[:4000], "commands": commands,
        }
        self._queue_reply(node_id, turn_id, reply, commands)

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
