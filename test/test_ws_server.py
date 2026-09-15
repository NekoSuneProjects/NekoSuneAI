"""The /wss endpoint, driven over a real socket pair.

Everything a device does over HTTP it can do here instead, on a connection
that outlives a long turn. These check that the authority does not change with
the transport: the same token, the same services, the same policy.
"""
from __future__ import annotations

import json
import socket
import threading
import time

import pytest

from nekosuneai.ws_hub import WebSocketHub
from nekosuneai.ws_protocol import (
    OP_TEXT,
    encode_frame,
    handshake_response,
    read_message,
)
from nekosuneai.ws_server import WS_PATHS, WebSocketEndpoint, wants_websocket


def wait_until(predicate, timeout=5.0):
    """auth.ok is sent before the hub registration, so give the server thread
    its moment rather than racing it."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


class FakeNodes:
    def __init__(self):
        self.token = "good-token"
        self.heartbeats = []
        self.acks = []
        self.capabilities = []

    def authorize(self, node_id, token):
        return node_id == "pi-1" and token == self.token

    def heartbeat(self, node_id, state, latency, battery, ip, ack):
        if state is None:
            self.acks.append(ack)
        else:
            self.heartbeats.append((node_id, state, ack))
        return {"node_id": node_id, "name": "Living Room Pi", "online": True}

    def update_capabilities(self, node_id, capabilities):
        self.capabilities.append(capabilities)


class FakeMedia:
    def handle(self, operation, payload):
        return {"ok": True, "operation": operation, "text": "transcribed"}


class FakeConverse:
    def __init__(self):
        self.seen = []

    def handle(self, node_id, payload):
        self.seen.append((node_id, payload))
        return {"ok": True, "reply": "Hello there.", "commands": []}


class Peer:
    """The device end of the connection."""

    def __init__(self, sock):
        self.sock = sock

    def send(self, message):
        self.sock.sendall(encode_frame(json.dumps(message).encode(), OP_TEXT, mask=True))

    def recv(self):
        result = read_message(self.sock)
        return None if result is None else json.loads(result[1])


class FakeHandler:
    """Enough of BaseHTTPRequestHandler for the endpoint to take over."""

    def __init__(self, sock, headers=None):
        self.connection = sock
        self.wfile = sock.makefile("wb")
        self.headers = headers if headers is not None else {
            "Connection": "Upgrade", "Upgrade": "websocket",
            "Sec-WebSocket-Key": "dGhlIHNhbXBsZSBub25jZQ==", "Sec-WebSocket-Version": "13",
        }
        self.close_connection = False


@pytest.fixture
def endpoint():
    nodes, media, converse = FakeNodes(), FakeMedia(), FakeConverse()
    hub = WebSocketHub()
    beats = []
    served = WebSocketEndpoint(
        hub, nodes, media, converse, on_heartbeat=lambda n, node: beats.append(n),
    )
    served.nodes_double, served.media_double, served.converse_double = nodes, media, converse
    served.hub_double, served.heartbeat_calls = hub, beats
    return served


@pytest.fixture
def connected(endpoint):
    """A started endpoint plus an authenticated device peer."""
    server_sock, client_sock = socket.socketpair()
    peer = Peer(client_sock)
    thread = threading.Thread(
        target=lambda: endpoint.handle(FakeHandler(server_sock)), daemon=True,
    )
    thread.start()

    # Consume the HTTP 101 that precedes the first frame.
    prefix = b""
    while b"\r\n\r\n" not in prefix:
        prefix += client_sock.recv(1)
    assert prefix.startswith(b"HTTP/1.1 101 Switching Protocols")

    peer.send({"type": "auth", "node_id": "pi-1", "token": "good-token"})
    assert peer.recv()["type"] == "auth.ok"
    try:
        yield endpoint, peer
    finally:
        client_sock.close()
        server_sock.close()


def test_only_an_upgrade_on_a_ws_path_is_taken_over():
    headers = {"Connection": "Upgrade", "Upgrade": "websocket"}
    assert wants_websocket("/wss", headers)
    assert wants_websocket("/ws", headers)          # both spellings served
    assert not wants_websocket("/api/nodes", headers)
    assert not wants_websocket("/wss", {"Connection": "keep-alive"})


def test_both_paths_are_offered():
    assert WS_PATHS == {"/wss", "/ws"}


def test_a_bad_token_is_refused_and_closed(endpoint):
    server_sock, client_sock = socket.socketpair()
    peer = Peer(client_sock)
    threading.Thread(target=lambda: endpoint.handle(FakeHandler(server_sock)), daemon=True).start()
    prefix = b""
    while b"\r\n\r\n" not in prefix:
        prefix += client_sock.recv(1)

    peer.send({"type": "auth", "node_id": "pi-1", "token": "wrong"})

    assert peer.recv() == {"type": "auth.error", "error": "unauthorized"}
    assert peer.recv() is None                       # then closed
    assert endpoint.hub_double.is_online("pi-1") is False
    client_sock.close()
    server_sock.close()


def test_a_non_auth_first_message_is_refused(endpoint):
    """Nothing is accepted before the device says who it is."""
    server_sock, client_sock = socket.socketpair()
    peer = Peer(client_sock)
    threading.Thread(target=lambda: endpoint.handle(FakeHandler(server_sock)), daemon=True).start()
    prefix = b""
    while b"\r\n\r\n" not in prefix:
        prefix += client_sock.recv(1)

    peer.send({"type": "converse", "text": "do something"})

    assert peer.recv()["type"] == "auth.error"
    assert endpoint.converse_double.seen == []
    client_sock.close()
    server_sock.close()


def test_an_authenticated_device_is_registered_in_the_hub(connected):
    endpoint, _peer = connected
    assert wait_until(lambda: endpoint.hub_double.is_online("pi-1"))


def test_a_converse_turn_answers_over_the_socket(connected):
    endpoint, peer = connected

    peer.send({"type": "converse", "id": "t1", "text": "hello", "speak": True})
    answer = peer.recv()

    assert answer["id"] == "t1"
    assert answer["reply"] == "Hello there."
    assert endpoint.converse_double.seen == [("pi-1", {"text": "hello", "speak": True})]


def test_a_heartbeat_updates_the_registry_and_runs_the_follow_on_work(connected):
    endpoint, peer = connected

    peer.send({
        "type": "heartbeat", "id": "h1",
        "state": {"music_playing": False}, "capabilities": {"audio.speak": {"kind": "write"}},
    })
    answer = peer.recv()

    assert answer["ok"] is True
    assert endpoint.nodes_double.heartbeats[0][0] == "pi-1"
    assert endpoint.nodes_double.capabilities == [{"audio.speak": {"kind": "write"}}]
    # The same follow-on work the HTTP route does, not a divergent copy.
    assert endpoint.heartbeat_calls == ["pi-1"]


def test_media_is_relayed_to_the_same_service(connected):
    endpoint, peer = connected

    peer.send({"type": "media", "id": "m1", "operation": "stt", "wav_base64": "AAA="})
    answer = peer.recv()

    assert answer["operation"] == "stt"
    assert answer["text"] == "transcribed"


def test_a_pushed_command_arrives_without_being_polled(connected):
    """The point of the socket: the backend initiates."""
    endpoint, peer = connected

    assert endpoint.hub_double.send("pi-1", {"type": "command", "command": {"id": 7}}) is True

    pushed = peer.recv()
    assert pushed == {"type": "command", "command": {"id": 7}}


def test_an_ack_reaches_the_registry(connected):
    endpoint, peer = connected

    peer.send({"type": "ack", "command_id": 12})
    peer.send({"type": "ping"})
    assert peer.recv() == {"type": "pong"}           # ordering proves it landed

    assert endpoint.nodes_double.acks == [12]


def test_malformed_json_does_not_drop_the_connection(connected):
    _endpoint, peer = connected

    peer.sock.sendall(encode_frame(b"{not json", OP_TEXT, mask=True))
    assert peer.recv()["error"] == "malformed JSON"

    peer.send({"type": "ping"})
    assert peer.recv() == {"type": "pong"}           # still usable


def test_an_unknown_message_type_is_reported_not_fatal(connected):
    _endpoint, peer = connected

    peer.send({"type": "teleport", "id": "x"})
    answer = peer.recv()

    assert answer["type"] == "error" and "unknown message type" in answer["error"]
    peer.send({"type": "ping"})
    assert peer.recv() == {"type": "pong"}


def test_a_failing_handler_reports_instead_of_closing(connected):
    endpoint, peer = connected
    endpoint.converse_double.handle = lambda node_id, payload: (_ for _ in ()).throw(
        RuntimeError("ollama is down")
    )

    peer.send({"type": "converse", "id": "t9", "text": "hello"})
    answer = peer.recv()

    assert answer["type"] == "error" and "ollama is down" in answer["error"]


def test_the_device_is_deregistered_when_it_disconnects(endpoint):
    server_sock, client_sock = socket.socketpair()
    peer = Peer(client_sock)
    thread = threading.Thread(
        target=lambda: endpoint.handle(FakeHandler(server_sock)), daemon=True,
    )
    thread.start()
    prefix = b""
    while b"\r\n\r\n" not in prefix:
        prefix += client_sock.recv(1)
    peer.send({"type": "auth", "node_id": "pi-1", "token": "good-token"})
    peer.recv()
    assert wait_until(lambda: endpoint.hub_double.is_online("pi-1"))

    client_sock.close()
    thread.join(timeout=5)

    assert endpoint.hub_double.is_online("pi-1") is False
    server_sock.close()


def test_the_handshake_is_a_valid_101_for_a_real_client():
    response = handshake_response({
        "Sec-WebSocket-Key": "dGhlIHNhbXBsZSBub25jZQ==", "Sec-WebSocket-Version": "13",
    })
    assert response.startswith(b"HTTP/1.1 101 Switching Protocols")


class TestPairedDeviceClients:
    """The Android app authenticates here too, but as a device.

    It pairs through DevicePairingManager rather than the node registry, so
    without this it could not use the socket at all -- and its chat request is
    exactly the long one a proxy cuts off. It gets the surface it already had
    over HTTP, and no more.
    """

    @pytest.fixture
    def device_endpoint(self):
        turns = []

        def run_device_turn(message, device_id):
            turns.append((message, device_id))
            return {"reply": "Hello from the backend.", "emotion": "warm", "gesture": "wave"}

        endpoint = WebSocketEndpoint(
            WebSocketHub(), FakeNodes(), FakeMedia(), FakeConverse(),
            authorize_device=lambda token: token == "device-token",
            run_device_turn=run_device_turn,
        )
        endpoint.turns = turns
        return endpoint

    def _connect(self, endpoint, auth):
        server_sock, client_sock = socket.socketpair()
        peer = Peer(client_sock)
        threading.Thread(target=lambda: endpoint.handle(FakeHandler(server_sock)), daemon=True).start()
        prefix = b""
        while b"\r\n\r\n" not in prefix:
            prefix += client_sock.recv(1)
        peer.send(auth)
        return peer, client_sock, server_sock

    def test_a_paired_device_authenticates_and_is_told_what_it_is(self, device_endpoint):
        peer, client_sock, server_sock = self._connect(device_endpoint, {
            "type": "auth", "device_id": "phone-1", "token": "device-token",
        })
        try:
            answer = peer.recv()
            assert answer["type"] == "auth.ok"
            assert answer["kind"] == "device"
            assert answer["id"] == "phone-1"
        finally:
            client_sock.close()
            server_sock.close()

    def test_a_device_chat_runs_the_same_turn_as_the_http_route(self, device_endpoint):
        peer, client_sock, server_sock = self._connect(device_endpoint, {
            "type": "auth", "device_id": "phone-1", "token": "device-token",
        })
        try:
            peer.recv()
            peer.send({"type": "chat", "id": "c1", "message": "hello"})
            answer = peer.recv()

            assert answer["reply"] == "Hello from the backend."
            assert answer["emotion"] == "warm"
            assert device_endpoint.turns == [("hello", "phone-1")]
        finally:
            client_sock.close()
            server_sock.close()

    def test_a_bad_device_token_is_refused(self, device_endpoint):
        peer, client_sock, server_sock = self._connect(device_endpoint, {
            "type": "auth", "device_id": "phone-1", "token": "wrong",
        })
        try:
            assert peer.recv()["type"] == "auth.error"
        finally:
            client_sock.close()
            server_sock.close()

    @pytest.mark.parametrize("kind", ["heartbeat", "converse", "media", "ack"])
    def test_a_device_cannot_reach_the_node_surface(self, device_endpoint, kind):
        """Upgrading the transport must not widen what a client can do."""
        peer, client_sock, server_sock = self._connect(device_endpoint, {
            "type": "auth", "device_id": "phone-1", "token": "device-token",
        })
        try:
            peer.recv()
            peer.send({"type": kind, "id": "x"})
            answer = peer.recv()

            assert answer["type"] == "error"
            assert "peripheral-node capability" in answer["error"]
        finally:
            client_sock.close()
            server_sock.close()

    def test_a_node_cannot_use_the_device_chat_surface(self, connected):
        """And the same in the other direction."""
        _endpoint, peer = connected

        peer.send({"type": "chat", "id": "c1", "message": "hello"})
        answer = peer.recv()

        assert answer["type"] == "error"
        assert "paired device" in answer["error"]
