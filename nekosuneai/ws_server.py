"""The `/wss` endpoint: one persistent connection per paired device.

Everything a device does over HTTP it can do here instead, over a connection
that survives a long turn. The reason is concrete: a converse turn runs web
search, the LLM and TTS, which regularly outlives a reverse proxy's *read*
timeout and gets answered 504 with the finished reply thrown away. A proxy
applies its far longer *idle* timeout to an upgraded connection, and the pings
below stop even that firing.

HTTP is not retired. It stays the fallback and remains the only way to pair,
because pairing is what issues the token this endpoint authenticates with.
A device that cannot reach `/wss` -- an old build, a proxy that will not
forward an upgrade -- keeps working exactly as before.

Wire protocol, JSON text frames unless noted:

    client -> server
      {"type": "auth",      "node_id", "token"}     first message, required
      {"type": "heartbeat", "state", "capabilities", "ack_command_id"}
      {"type": "converse",  "text", "speak", "id"}
      {"type": "media",     "operation", "id", ...} stt / tts / vision
      {"type": "ack",       "command_id"}
      {"type": "ping"}

    server -> client
      {"type": "auth.ok",   "node_id", "server_epoch"}
      {"type": "auth.error","error"}                then close
      {"type": "command",   "command"}              pushed, not polled
      {"type": "result",    "id", "ok", ...}        answers converse/media
      {"type": "error",     "id", "error"}
      {"type": "pong"}

An authenticated socket carries exactly the authority the device's token
already had: every request is dispatched through the same services the HTTP
routes use, so capability policy, rate limits and media bounds all still
apply. Upgrading the transport is not a way around any of them.
"""
from __future__ import annotations

import json
import threading
import time
from typing import Any

from .ws_hub import PING_INTERVAL_SECONDS, PONG_TIMEOUT_SECONDS, WebSocketConnection
from .ws_protocol import (
    CLOSE_PROTOCOL_ERROR,
    CLOSE_UNAUTHORIZED,
    OP_PING,
    OP_PONG,
    OP_TEXT,
    WebSocketError,
    handshake_response,
    is_upgrade_request,
    read_message,
)

# Both spellings are served: the owner asked for /wss, and /ws is what most
# client libraries and proxy examples assume.
WS_PATHS = frozenset({"/wss", "/ws"})

# A device must identify itself before it can do anything else. Without a
# deadline an unauthenticated socket could sit holding a thread indefinitely.
AUTH_TIMEOUT_SECONDS = 15.0


class WebSocketEndpoint:
    """Serves upgrade requests and runs each connection's message loop."""

    def __init__(
        self,
        hub: Any,
        nodes: Any,
        node_media: Any,
        node_converse: Any,
        on_heartbeat: Any = None,
    ) -> None:
        self.hub = hub
        self.nodes = nodes
        self.node_media = node_media
        self.node_converse = node_converse
        # webserver.py does more on a heartbeat than the registry does --
        # routines, the timeline, Twitch chat ingest -- so that work is passed
        # in rather than duplicated here and allowed to drift.
        self.on_heartbeat = on_heartbeat

    # ── lifecycle ─────────────────────────────────────────────────────────

    def handle(self, handler: Any) -> None:
        """Take over an HTTP handler's socket and serve it as a WebSocket.

        Runs on the handler's own thread for the life of the connection, which
        is what ThreadingHTTPServer's thread-per-connection model gives us.
        """
        try:
            handler.wfile.write(handshake_response(handler.headers))
            handler.wfile.flush()
        except (WebSocketError, OSError):
            return

        sock = handler.connection
        # Reads block on the message loop, so the socket needs a timeout long
        # enough for a quiet-but-healthy link and short enough to notice a dead
        # one. The keepalive below runs well inside it.
        sock.settimeout(PONG_TIMEOUT_SECONDS)
        connection = WebSocketConnection("", sock)

        try:
            node_id = self._authenticate(connection)
            if not node_id:
                return
            connection.device_id = node_id
            self.hub.add(connection)
            keepalive = self._start_keepalive(connection)
            try:
                self._serve(connection)
            finally:
                keepalive.set()
        except (WebSocketError, OSError, ValueError):
            pass
        finally:
            self.hub.remove(connection)
            connection.close()

    def _authenticate(self, connection: WebSocketConnection) -> str:
        """Require a valid auth message before anything else is accepted."""
        deadline = time.monotonic() + AUTH_TIMEOUT_SECONDS
        connection.sock.settimeout(AUTH_TIMEOUT_SECONDS)
        try:
            message = self._read_json(connection)
        except (WebSocketError, OSError, ValueError):
            message = None
        connection.sock.settimeout(PONG_TIMEOUT_SECONDS)

        if not message or str(message.get("type")) != "auth" or time.monotonic() > deadline:
            connection.send_json({"type": "auth.error", "error": "an auth message is required first"})
            connection.close(CLOSE_UNAUTHORIZED, "auth required")
            return ""

        node_id = str(message.get("node_id", ""))
        token = str(message.get("token", ""))
        if not self.nodes.authorize(node_id, token):
            # Same check and same answer as the HTTP routes: a socket is not a
            # softer door than a request.
            connection.send_json({"type": "auth.error", "error": "unauthorized node"})
            connection.close(CLOSE_UNAUTHORIZED, "unauthorized")
            return ""

        connection.send_json({
            "type": "auth.ok", "node_id": node_id, "server_epoch": time.time(),
        })
        return node_id

    def _start_keepalive(self, connection: WebSocketConnection) -> threading.Event:
        """Ping periodically so a proxy never sees the connection as idle."""
        stop = threading.Event()

        def run() -> None:
            while not stop.wait(PING_INTERVAL_SECONDS):
                if connection.closed:
                    return
                if time.time() - connection.last_pong > PONG_TIMEOUT_SECONDS:
                    # Half-open: a NAT stopped forwarding and nothing told us.
                    connection.close(1001, "no pong")
                    return
                try:
                    connection.ping()
                except WebSocketError:
                    return

        threading.Thread(
            target=run, daemon=True, name=f"ws-keepalive-{connection.device_id}",
        ).start()
        return stop

    def _read_json(self, connection: WebSocketConnection) -> dict[str, Any] | None:
        def on_control(opcode: int, payload: bytes) -> None:
            if opcode == OP_PING:
                connection.pong(payload)
            elif opcode == OP_PONG:
                connection.last_pong = time.time()

        result = read_message(connection.sock, on_control=on_control)
        if result is None:
            return None
        opcode, body = result
        if opcode != OP_TEXT:
            return {}
        decoded = json.loads(body.decode("utf-8"))
        return decoded if isinstance(decoded, dict) else {}

    def _serve(self, connection: WebSocketConnection) -> None:
        while not connection.closed:
            try:
                message = self._read_json(connection)
            except json.JSONDecodeError:
                connection.send_json({"type": "error", "error": "malformed JSON"})
                continue
            except TimeoutError:
                # The keepalive decides whether the peer is actually gone; a
                # quiet link is normal between turns.
                continue
            if message is None:
                return
            if not message:
                continue
            try:
                self._dispatch(connection, message)
            except Exception as exc:
                connection.send_json({
                    "type": "error", "id": message.get("id"), "error": str(exc)[:300],
                })

    # ── message handling ──────────────────────────────────────────────────

    def _dispatch(self, connection: WebSocketConnection, message: dict[str, Any]) -> None:
        kind = str(message.get("type", ""))
        node_id = connection.device_id
        request_id = message.get("id")

        if kind == "ping":
            connection.send_json({"type": "pong"})
            return

        if kind == "ack":
            self.nodes.heartbeat(
                node_id, None, None, None, "", int(message.get("command_id") or 0),
            )
            return

        if kind == "heartbeat":
            if "capabilities" in message:
                self.nodes.update_capabilities(node_id, message["capabilities"])
            node = self.nodes.heartbeat(
                node_id, dict(message.get("state") or {}),
                message.get("latency_ms"), message.get("battery_percent"), "",
                message.get("ack_command_id"),
            )
            if self.on_heartbeat is not None:
                self.on_heartbeat(node_id, node)
            connection.send_json({"type": "result", "id": request_id, "ok": True, "node": node})
            return

        if kind == "converse":
            # Runs on this connection's own thread, so a long turn blocks only
            # this device -- and the keepalive thread keeps pinging throughout,
            # which is the entire point of doing this over a socket.
            result = self.node_converse.handle(node_id, {
                "text": message.get("text", ""), "speak": message.get("speak", True),
            })
            connection.send_json({"type": "result", "id": request_id, **result})
            return

        if kind == "media":
            operation = str(message.get("operation", ""))
            payload = {key: value for key, value in message.items()
                       if key not in {"type", "operation", "id"}}
            payload["node_id"] = node_id
            result = self.node_media.handle(operation, payload)
            connection.send_json({"type": "result", "id": request_id, **result})
            return

        connection.send_json({
            "type": "error", "id": request_id, "error": f"unknown message type: {kind[:40]}",
        })


def wants_websocket(path: str, headers: Any) -> bool:
    """Whether this GET should become a WebSocket rather than a page."""
    return path in WS_PATHS and is_upgrade_request(headers)
