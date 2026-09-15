"""Live WebSocket connections to paired devices, and pushing to them.

One entry per connected device, keyed by the id it paired with, so the backend
can address a specific one: the Pi in the living room, the phone in a pocket,
the Windows box. That is the whole point -- a reply belongs to the device that
asked, and until now the only way to reach one was to wait for it to poll.

What this deliberately does not change:

* Authentication. A socket is authenticated with the same device token the
  HTTP endpoints take, checked by the same registry. Upgrading the transport
  must not become a way around pairing.
* Authority. Commands pushed down a socket are still filtered through the
  owner's capability policy by the caller, exactly as the queued ones are.
* Durability. The command queue remains the source of truth. A socket is a
  fast path for delivery, not a replacement for it -- a device that was
  offline still collects its commands on the next poll.
"""
from __future__ import annotations

import json
import threading
import time
from typing import Any

from .ws_protocol import (
    OP_BINARY,
    OP_PING,
    OP_PONG,
    OP_TEXT,
    WebSocketError,
    close_frame,
    encode_frame,
)

# Sent when a connection has been quiet this long. A reverse proxy will drop an
# idle upgraded connection eventually, and the whole reason for using a socket
# is to outlive a long turn, so it must not be idle during one.
PING_INTERVAL_SECONDS = 25.0
# A device that has not answered a ping in this long is treated as gone, so a
# half-open connection through a NAT that silently stopped forwarding does not
# keep absorbing pushes that will never arrive.
PONG_TIMEOUT_SECONDS = 70.0


class WebSocketConnection:
    """One device's socket. Writes are serialised; reads belong to its thread."""

    def __init__(self, device_id: str, sock: Any, kind: str = "node") -> None:
        self.device_id = device_id
        self.kind = kind
        self.sock = sock
        self.connected_epoch = time.time()
        self.last_pong = time.time()
        self._write_lock = threading.Lock()
        self._closed = False

    @property
    def closed(self) -> bool:
        return self._closed

    def send_bytes(self, payload: bytes, opcode: int = OP_TEXT) -> None:
        with self._write_lock:
            if self._closed:
                raise WebSocketError("connection is closed")
            try:
                self.sock.sendall(encode_frame(payload, opcode))
            except OSError as exc:
                self._closed = True
                raise WebSocketError(f"send failed: {exc}") from exc

    def send_json(self, message: dict[str, Any]) -> None:
        self.send_bytes(json.dumps(message, default=str).encode("utf-8"), OP_TEXT)

    def send_binary(self, payload: bytes) -> None:
        """Audio and other blobs, sent as-is rather than base64 in JSON.

        A WAV through JSON costs a third more bytes and an encode/decode on
        both ends; a binary frame is what the protocol has them for.
        """
        self.send_bytes(payload, OP_BINARY)

    def ping(self) -> None:
        self.send_bytes(b"", OP_PING)

    def pong(self, payload: bytes = b"") -> None:
        self.send_bytes(payload, OP_PONG)

    def close(self, code: int = 1000, reason: str = "") -> None:
        with self._write_lock:
            if self._closed:
                return
            self._closed = True
            try:
                self.sock.sendall(close_frame(code, reason))
            except OSError:
                pass
            try:
                self.sock.close()
            except OSError:
                pass


class WebSocketHub:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._connections: dict[str, WebSocketConnection] = {}

    def add(self, connection: WebSocketConnection) -> None:
        """Register a connection, replacing any older one for the same device.

        A device that reconnects without its previous socket having been
        noticed as dead -- a Pi rebooting, a phone changing network -- would
        otherwise leave a stale entry that pushes vanish into.
        """
        with self._lock:
            previous = self._connections.get(connection.device_id)
            self._connections[connection.device_id] = connection
        if previous is not None and previous is not connection:
            previous.close(1001, "replaced by a new connection")

    def remove(self, connection: WebSocketConnection) -> None:
        with self._lock:
            current = self._connections.get(connection.device_id)
            if current is connection:
                self._connections.pop(connection.device_id, None)

    def get(self, device_id: str) -> WebSocketConnection | None:
        with self._lock:
            connection = self._connections.get(str(device_id))
        return None if connection is not None and connection.closed else connection

    def is_online(self, device_id: str) -> bool:
        return self.get(device_id) is not None

    def send(self, device_id: str, message: dict[str, Any]) -> bool:
        """Push to one device. False when it has no live socket.

        False is not an error: the caller falls back to the command queue,
        which is still the durable path.
        """
        connection = self.get(device_id)
        if connection is None:
            return False
        try:
            connection.send_json(message)
            return True
        except WebSocketError:
            self.remove(connection)
            connection.close()
            return False

    def send_binary(self, device_id: str, payload: bytes) -> bool:
        connection = self.get(device_id)
        if connection is None:
            return False
        try:
            connection.send_binary(payload)
            return True
        except WebSocketError:
            self.remove(connection)
            connection.close()
            return False

    def connections(self) -> list[dict[str, Any]]:
        """Read-only view for the dashboard and /api/nodes."""
        with self._lock:
            live = list(self._connections.values())
        return [
            {
                "device_id": item.device_id,
                "kind": item.kind,
                "connected_epoch": item.connected_epoch,
                "idle_seconds": round(time.time() - item.last_pong, 1),
            }
            for item in live
            if not item.closed
        ]

    def close_all(self, reason: str = "server shutting down") -> None:
        with self._lock:
            live = list(self._connections.values())
            self._connections.clear()
        for connection in live:
            connection.close(1001, reason)
