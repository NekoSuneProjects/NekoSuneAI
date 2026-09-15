"""Persistent WebSocket link to the Docker backend, with HTTP as the fallback.

Why this exists, for a gaming node specifically: commands arrive pushed the
moment the backend queues them rather than on the next poll, which on this
node is the difference between an in-game action landing now and landing up to
a poll interval late. The same connection also carries vision and speech
requests, which are long enough to be cut off by a reverse proxy's *read*
timeout -- a proxy applies its far longer *idle* timeout to an upgraded
connection, and the keepalive below stops even that firing.

The URL is derived from the backend address already configured for HTTP --
`https://host` becomes `wss://host/wss` -- so there is nothing extra to set up
and no second address to keep in step when the backend moves.

HTTP is not replaced. This connects opportunistically and every caller keeps
its HTTP path: if the socket is down, or a proxy will not forward an upgrade,
or the backend predates this endpoint, the node behaves exactly as it did
before. That is why `request()` raises rather than blocking when it is not
connected -- the caller is expected to fall back, not to wait.
"""
from __future__ import annotations

import json
import os
import secrets
import socket
import ssl
import threading
import time
from typing import Any, Callable
from urllib.parse import urlsplit

from .ws_protocol import (
    OP_BINARY,
    OP_PING,
    OP_PONG,
    OP_TEXT,
    WebSocketError,
    accept_key,
    encode_frame,
    read_message,
)

# Well inside the 60s a proxy typically allows an idle upgraded connection.
PING_INTERVAL_SECONDS = 20.0
# Reconnect backoff: quick enough that a backend restart is barely noticed,
# capped so a backend that is genuinely down is not hammered.
RECONNECT_MIN_SECONDS = 2.0
RECONNECT_MAX_SECONDS = 60.0
# A turn can legitimately take minutes; this only bounds a request whose reply
# never arrives at all.
REQUEST_TIMEOUT_SECONDS = 300.0
HANDSHAKE_TIMEOUT_SECONDS = 20.0


def websocket_url(server_url: str, path: str = "/wss") -> str:
    """Derive the socket address from the configured backend address.

    https -> wss and http -> ws, keeping host, port and any base path, so the
    owner configures one address rather than two that can fall out of step.
    """
    parts = urlsplit(str(server_url or "").strip())
    if not parts.scheme or not parts.netloc:
        raise ValueError(f"cannot derive a WebSocket URL from {server_url!r}")
    scheme = "wss" if parts.scheme.lower() in ("https", "wss") else "ws"
    base = parts.path.rstrip("/")
    return f"{scheme}://{parts.netloc}{base}{path}"


class WebSocketClient:
    """One background connection, reconnecting on its own.

    Requests are correlated by id so several can be outstanding at once, which
    matters because the backend pushes commands on the same socket while a
    long converse turn is still waiting for its answer.
    """

    def __init__(
        self,
        server_url: str,
        node_id: str,
        token_provider: Callable[[], str],
        on_command: Callable[[dict[str, Any]], None],
        verify_tls: bool = True,
        notify: Callable[[str], None] | None = None,
    ) -> None:
        self.server_url = server_url
        self.node_id = node_id
        self.token_provider = token_provider
        self.on_command = on_command
        self.verify_tls = verify_tls
        self.notify = notify or (lambda message: None)

        self._sock: socket.socket | None = None
        self._send_lock = threading.Lock()
        self._stop = threading.Event()
        self._connected = threading.Event()
        self._thread: threading.Thread | None = None
        self._pending: dict[str, dict[str, Any]] = {}
        self._pending_lock = threading.Lock()
        self.last_error = ""
        self.connected_since = 0.0
        self.reconnects = 0

    # ── state ─────────────────────────────────────────────────────────────

    @property
    def connected(self) -> bool:
        return self._connected.is_set()

    def status(self) -> dict[str, Any]:
        return {
            "enabled": True,
            "connected": self.connected,
            "url": self._safe_url(),
            "connected_since": self.connected_since,
            "reconnects": self.reconnects,
            "error": self.last_error,
        }

    def _safe_url(self) -> str:
        try:
            return websocket_url(self.server_url)
        except ValueError:
            return ""

    # ── lifecycle ─────────────────────────────────────────────────────────

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="windows-node-ws")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._close_socket()

    def _run(self) -> None:
        delay = RECONNECT_MIN_SECONDS
        while not self._stop.is_set():
            if not self.token_provider():
                # Unpaired: nothing to authenticate with yet. Wait rather than
                # burning reconnect attempts against a socket that would only
                # be refused.
                if self._stop.wait(5):
                    return
                continue
            try:
                self._connect_and_serve()
                delay = RECONNECT_MIN_SECONDS
            except Exception as exc:
                self.last_error = str(exc)[:200]
            finally:
                was_connected = self._connected.is_set()
                self._connected.clear()
                self._close_socket()
                self._fail_pending("the connection dropped")
            if self._stop.is_set():
                return
            if was_connected:
                self.reconnects += 1
            if self._stop.wait(delay):
                return
            delay = min(delay * 2, RECONNECT_MAX_SECONDS)

    def _connect_and_serve(self) -> None:
        url = websocket_url(self.server_url)
        parts = urlsplit(url)
        secure = parts.scheme == "wss"
        host = parts.hostname or ""
        port = parts.port or (443 if secure else 80)

        sock = socket.create_connection((host, port), timeout=HANDSHAKE_TIMEOUT_SECONDS)
        if secure:
            context = ssl.create_default_context()
            if not self.verify_tls:
                context.check_hostname = False
                context.verify_mode = ssl.CERT_NONE
            sock = context.wrap_socket(sock, server_hostname=host)

        key = secrets.token_bytes(16)
        self._handshake(sock, parts, host, port, key)
        # Long enough that a quiet link between turns is not mistaken for a
        # dead one; the keepalive runs well inside it.
        sock.settimeout(PING_INTERVAL_SECONDS * 3)
        self._sock = sock

        self._send_json({"type": "auth", "node_id": self.node_id, "token": self.token_provider()})
        first = self._read_json()
        if not first or first.get("type") != "auth.ok":
            raise WebSocketError(str((first or {}).get("error") or "authentication failed"))

        self._connected.set()
        self.connected_since = time.time()
        self.last_error = ""
        self.notify(f"live connection to {host} established")
        keepalive = self._start_keepalive()
        try:
            self._serve()
        finally:
            keepalive.set()

    def _handshake(self, sock: socket.socket, parts: Any, host: str, port: int, key: bytes) -> None:
        import base64

        encoded = base64.b64encode(key).decode("ascii")
        target = parts.path or "/wss"
        request = (
            f"GET {target} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {encoded}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "\r\n"
        )
        sock.sendall(request.encode("ascii"))

        response = b""
        while b"\r\n\r\n" not in response:
            chunk = sock.recv(1)
            if not chunk:
                raise WebSocketError("the server closed the connection during the handshake")
            response += chunk
            if len(response) > 8192:
                raise WebSocketError("handshake response was implausibly large")

        head = response.decode("latin-1")
        status = head.split("\r\n", 1)[0]
        if "101" not in status:
            # The common cause is a proxy that will not forward an upgrade, so
            # say what was actually received rather than "connection failed".
            raise WebSocketError(f"server refused the upgrade: {status.strip()}")
        expected = accept_key(encoded).lower()
        if expected not in head.lower():
            raise WebSocketError("the server's handshake did not match our key")

    def _close_socket(self) -> None:
        sock, self._sock = self._sock, None
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass

    # ── framing ───────────────────────────────────────────────────────────

    def _send_json(self, message: dict[str, Any]) -> None:
        sock = self._sock
        if sock is None:
            raise WebSocketError("not connected")
        payload = json.dumps(message, default=str).encode("utf-8")
        with self._send_lock:
            # Client-to-server frames must be masked (RFC 6455); servers
            # disconnect over an unmasked one.
            sock.sendall(encode_frame(payload, OP_TEXT, mask=True))

    def _read_json(self) -> dict[str, Any] | None:
        sock = self._sock
        if sock is None:
            return None

        def on_control(opcode: int, payload: bytes) -> None:
            if opcode == OP_PING:
                with self._send_lock:
                    sock.sendall(encode_frame(payload, OP_PONG, mask=True))

        result = read_message(sock, on_control=on_control)
        if result is None:
            return None
        opcode, body = result
        if opcode == OP_BINARY:
            return {"type": "binary", "data": body}
        decoded = json.loads(body.decode("utf-8"))
        return decoded if isinstance(decoded, dict) else {}

    def _start_keepalive(self) -> threading.Event:
        stop = threading.Event()

        def run() -> None:
            while not stop.wait(PING_INTERVAL_SECONDS):
                sock = self._sock
                if sock is None:
                    return
                try:
                    with self._send_lock:
                        sock.sendall(encode_frame(b"", OP_PING, mask=True))
                except OSError:
                    return

        threading.Thread(target=run, daemon=True, name="windows-node-ws-ping").start()
        return stop

    # ── message loop ──────────────────────────────────────────────────────

    def _serve(self) -> None:
        while not self._stop.is_set():
            try:
                message = self._read_json()
            except TimeoutError:
                continue
            except json.JSONDecodeError:
                continue
            if message is None:
                return
            if not message:
                continue
            self._handle(message)

    def _handle(self, message: dict[str, Any]) -> None:
        kind = str(message.get("type", ""))
        if kind == "command":
            # Dispatched on its own thread so a slow command -- resolving a
            # stream, speaking a long reply -- does not stall this socket and
            # let the keepalive lapse.
            command = dict(message.get("command") or {})
            threading.Thread(
                target=self._run_command, args=(command,), daemon=True, name="windows-node-ws-command",
            ).start()
            return
        if kind == "pong":
            return

        request_id = str(message.get("id") or "")
        if not request_id:
            return
        with self._pending_lock:
            waiter = self._pending.pop(request_id, None)
        if waiter is not None:
            waiter["result"] = message
            waiter["event"].set()

    def _run_command(self, command: dict[str, Any]) -> None:
        try:
            self.on_command(command)
        except Exception as exc:
            self.last_error = f"command failed: {exc}"[:200]

    def _fail_pending(self, reason: str) -> None:
        with self._pending_lock:
            waiting = list(self._pending.values())
            self._pending.clear()
        for waiter in waiting:
            waiter["result"] = {"type": "error", "error": reason}
            waiter["event"].set()

    # ── requests ──────────────────────────────────────────────────────────

    def request(self, message: dict[str, Any], timeout: float = REQUEST_TIMEOUT_SECONDS) -> dict[str, Any]:
        """Send a message and wait for its correlated answer.

        Raises when the socket is not usable, which is the signal for the
        caller to take its HTTP path instead. It never blocks waiting to
        reconnect: falling back immediately is better than making the owner
        wait for a transport detail.
        """
        if not self.connected:
            raise WebSocketError("not connected")
        request_id = secrets.token_hex(8)
        waiter = {"event": threading.Event(), "result": None}
        with self._pending_lock:
            self._pending[request_id] = waiter
        try:
            self._send_json({**message, "id": request_id})
        except Exception:
            with self._pending_lock:
                self._pending.pop(request_id, None)
            raise

        if not waiter["event"].wait(timeout):
            with self._pending_lock:
                self._pending.pop(request_id, None)
            raise WebSocketError("timed out waiting for the backend to answer")

        result = waiter["result"] or {}
        if result.get("type") == "error":
            raise RuntimeError(str(result.get("error") or "the backend reported an error"))
        return result

    def send(self, message: dict[str, Any]) -> bool:
        """Fire-and-forget. False when there is no usable connection."""
        if not self.connected:
            return False
        try:
            self._send_json(message)
            return True
        except Exception:
            return False
