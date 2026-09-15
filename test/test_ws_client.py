"""This node's live link to the backend, and its fallback behaviour.

Commands arrive pushed rather than polled, which on a gaming node is the
difference between an action landing now and landing a poll interval late.
The link is opportunistic -- every caller keeps its HTTP path -- so these
check just as hard that failing over is clean as that connecting works.
"""
from __future__ import annotations

import json
import socket
import threading
import time

import pytest

from nekosuneai.ws_client import WebSocketClient, websocket_url
from nekosuneai.ws_protocol import (
    OP_PING,
    OP_TEXT,
    WebSocketError,
    accept_key,
    encode_frame,
    read_message,
)


@pytest.mark.parametrize(
    ("configured", "expected"),
    [
        ("https://neko.example.com", "wss://neko.example.com/wss"),
        ("https://neko.example.com/", "wss://neko.example.com/wss"),
        ("http://192.168.1.5:8788", "ws://192.168.1.5:8788/wss"),
        ("https://neko.example.com:8443", "wss://neko.example.com:8443/wss"),
        ("https://neko.example.com/base/", "wss://neko.example.com/base/wss"),
    ],
)
def test_the_socket_address_is_derived_from_the_backend_address(configured, expected):
    """One configured address, not two that can fall out of step."""
    assert websocket_url(configured) == expected


@pytest.mark.parametrize("bad", ["", "   ", "neko.example.com", "not a url"])
def test_an_unusable_address_is_rejected(bad):
    with pytest.raises(ValueError):
        websocket_url(bad)


class FakeBackend:
    """A minimal /wss server: handshake, auth, then scripted answers."""

    def __init__(self, token="good-token", refuse_upgrade=False):
        self.listener = socket.socket()
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(1)
        self.port = self.listener.getsockname()[1]
        self.token = token
        self.refuse_upgrade = refuse_upgrade
        self.received: list[dict] = []
        self.authed = threading.Event()
        self.conn: socket.socket | None = None
        self._stop = threading.Event()
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    @property
    def url(self):
        return f"http://127.0.0.1:{self.port}"

    def _serve(self):
        try:
            conn, _ = self.listener.accept()
        except OSError:
            return
        self.conn = conn
        request = b""
        while b"\r\n\r\n" not in request:
            chunk = conn.recv(1)
            if not chunk:
                return
            request += chunk

        if self.refuse_upgrade:
            # What a proxy that will not forward an upgrade actually sends.
            conn.sendall(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\n\r\n")
            return

        key = ""
        for line in request.decode("latin-1").split("\r\n"):
            if line.lower().startswith("sec-websocket-key:"):
                key = line.split(":", 1)[1].strip()
        conn.sendall((
            "HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n"
            f"Connection: Upgrade\r\nSec-WebSocket-Accept: {accept_key(key)}\r\n\r\n"
        ).encode())

        while not self._stop.is_set():
            try:
                result = read_message(conn)
            except (OSError, WebSocketError):
                return
            if result is None:
                return
            try:
                message = json.loads(result[1])
            except ValueError:
                continue
            self.received.append(message)
            self._answer(conn, message)

    def _answer(self, conn, message):
        kind = message.get("type")
        if kind == "auth":
            ok = message.get("token") == self.token
            self.send(conn, {"type": "auth.ok", "node_id": message.get("node_id")} if ok
                      else {"type": "auth.error", "error": "unauthorized node"})
            if ok:
                self.authed.set()
            return
        if kind == "converse":
            self.send(conn, {
                "type": "result", "id": message.get("id"), "ok": True,
                "turn_id": "t1", "reply": "Hello there.", "commands": [],
            })
        elif kind == "media":
            self.send(conn, {
                "type": "result", "id": message.get("id"), "ok": True, "text": "transcribed",
            })

    @staticmethod
    def send(conn, message):
        conn.sendall(encode_frame(json.dumps(message).encode(), OP_TEXT))

    def push(self, message):
        self.send(self.conn, message)

    def close(self):
        self._stop.set()
        for sock in (self.conn, self.listener):
            try:
                sock and sock.close()
            except OSError:
                pass


@pytest.fixture
def backend():
    server = FakeBackend()
    yield server
    server.close()


def make_client(backend, token="good-token", on_command=None):
    return WebSocketClient(
        server_url=backend.url, node_id="win-1", token_provider=lambda: token,
        on_command=on_command or (lambda command: None), verify_tls=False,
    )


def wait_for(predicate, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def test_the_client_connects_and_authenticates(backend):
    client = make_client(backend)
    client.start()
    try:
        assert wait_for(lambda: client.connected), client.last_error
        assert backend.received[0]["type"] == "auth"
        assert backend.received[0]["token"] == "good-token"
        assert client.status()["url"].endswith("/wss")
    finally:
        client.stop()


def test_a_request_gets_its_correlated_answer(backend):
    client = make_client(backend)
    client.start()
    try:
        assert wait_for(lambda: client.connected)

        result = client.request({"type": "converse", "text": "hello"}, timeout=5)

        assert result["reply"] == "Hello there."
        assert result["turn_id"] == "t1"
    finally:
        client.stop()


def test_a_pushed_command_is_dispatched_without_being_asked_for(backend):
    """The point of the socket: the backend initiates."""
    seen: list[dict] = []
    client = make_client(backend, on_command=seen.append)
    client.start()
    try:
        assert wait_for(lambda: client.connected)

        backend.push({"type": "command", "command": {"id": 5, "capability": "music.stop"}})

        assert wait_for(lambda: seen)
        assert seen[0]["capability"] == "music.stop"
    finally:
        client.stop()


def test_a_request_while_disconnected_raises_so_the_caller_falls_back(backend):
    """It must not block waiting to reconnect -- HTTP is right there."""
    client = make_client(backend)

    with pytest.raises(WebSocketError, match="not connected"):
        client.request({"type": "converse", "text": "hello"})
    assert client.send({"type": "ack", "command_id": 1}) is False


def test_a_refused_upgrade_is_reported_with_what_the_proxy_said():
    """The usual cause is a proxy not forwarding the upgrade; say which."""
    server = FakeBackend(refuse_upgrade=True)
    client = make_client(server)
    client.start()
    try:
        assert wait_for(lambda: "502" in client.last_error, timeout=6), client.last_error
        assert client.connected is False
    finally:
        client.stop()
        server.close()


def test_a_bad_token_does_not_leave_the_client_claiming_to_be_connected(backend):
    client = make_client(backend, token="wrong")
    client.start()
    try:
        assert wait_for(lambda: "unauthorized" in client.last_error, timeout=6), client.last_error
        assert client.connected is False
    finally:
        client.stop()


def test_an_unpaired_node_does_not_burn_reconnect_attempts(backend):
    """No token means nothing to authenticate with; waiting beats retrying."""
    client = WebSocketClient(
        server_url=backend.url, node_id="win-1", token_provider=lambda: "",
        on_command=lambda command: None, verify_tls=False,
    )
    client.start()
    try:
        time.sleep(0.5)
        assert client.connected is False
        assert backend.received == []
    finally:
        client.stop()


def test_a_dropped_connection_fails_waiting_requests_rather_than_hanging(backend):
    client = make_client(backend)
    client.start()
    assert wait_for(lambda: client.connected)

    errors: list[Exception] = []

    def ask():
        try:
            client.request({"type": "heartbeat", "state": {}}, timeout=10)
        except Exception as exc:      # noqa: BLE001 - recorded for the assert
            errors.append(exc)

    # A heartbeat gets no scripted answer from this backend, so the request
    # is genuinely outstanding when the socket dies.
    asker = threading.Thread(target=ask, daemon=True)
    asker.start()
    time.sleep(0.3)
    backend.close()

    asker.join(timeout=8)
    client.stop()
    assert errors, "a dropped connection must fail the request, not hang it"


def test_a_ping_from_the_backend_is_answered(backend):
    """Silence here is what makes a proxy drop the connection as idle."""
    client = make_client(backend)
    client.start()
    try:
        assert wait_for(lambda: client.connected)
        before = len(backend.received)

        backend.conn.sendall(encode_frame(b"", OP_PING))
        # A pong is a control frame, so it does not land in `received`; what
        # matters is that the connection survives and still works.
        time.sleep(0.3)
        result = client.request({"type": "converse", "text": "hello"}, timeout=5)

        assert result["reply"] == "Hello there."
        assert len(backend.received) > before
    finally:
        client.stop()
