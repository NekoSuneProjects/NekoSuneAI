"""The registry of live device connections, and pushing to a named device."""
from __future__ import annotations

import json

import pytest

from nekosuneai.ws_hub import WebSocketConnection, WebSocketHub
from nekosuneai.ws_protocol import OP_BINARY, OP_TEXT, read_frame


class FakeSock:
    def __init__(self, fail: bool = False):
        self.sent = bytearray()
        self.closed = False
        self.fail = fail

    def sendall(self, data: bytes) -> None:
        if self.fail:
            raise OSError("broken pipe")
        self.sent.extend(data)

    def close(self) -> None:
        self.closed = True


class Reader:
    """Replays a connection's written bytes back through the frame decoder."""

    def __init__(self, data: bytes):
        self.data, self.position = data, 0

    def recv(self, count: int) -> bytes:
        out = self.data[self.position:self.position + count]
        self.position += len(out)
        return out


def connection(device_id="pi-1", fail=False):
    sock = FakeSock(fail=fail)
    return WebSocketConnection(device_id, sock, kind="node"), sock


def test_a_push_reaches_the_named_device():
    hub = WebSocketHub()
    live, sock = connection("pi-1")
    hub.add(live)

    assert hub.send("pi-1", {"type": "reply", "text": "hello"}) is True

    opcode, payload, _fin = read_frame(Reader(bytes(sock.sent)))
    assert opcode == OP_TEXT
    assert json.loads(payload) == {"type": "reply", "text": "hello"}


def test_pushing_to_an_unknown_device_reports_false_rather_than_raising():
    """False means "fall back to the queue", which is the durable path."""
    assert WebSocketHub().send("nobody", {"type": "reply"}) is False


def test_audio_is_sent_as_a_binary_frame():
    """A WAV through JSON costs a third more bytes for no benefit."""
    hub = WebSocketHub()
    live, sock = connection("pi-1")
    hub.add(live)

    assert hub.send_binary("pi-1", b"RIFF....WAVE") is True

    opcode, payload, _fin = read_frame(Reader(bytes(sock.sent)))
    assert (opcode, payload) == (OP_BINARY, b"RIFF....WAVE")


def test_reconnecting_replaces_and_closes_the_stale_connection():
    """A Pi that reboots would otherwise leave an entry pushes vanish into."""
    hub = WebSocketHub()
    old, old_sock = connection("pi-1")
    hub.add(old)

    new, _new_sock = connection("pi-1")
    hub.add(new)

    assert old.closed and old_sock.closed
    assert hub.get("pi-1") is new


def test_a_failed_send_drops_the_connection():
    hub = WebSocketHub()
    live, _sock = connection("pi-1", fail=True)
    hub.add(live)

    assert hub.send("pi-1", {"type": "reply"}) is False
    assert hub.get("pi-1") is None
    assert hub.is_online("pi-1") is False


def test_removing_a_replaced_connection_does_not_evict_its_successor():
    """The old socket's own thread calls remove() after being replaced."""
    hub = WebSocketHub()
    old, _ = connection("pi-1")
    hub.add(old)
    new, _ = connection("pi-1")
    hub.add(new)

    hub.remove(old)

    assert hub.get("pi-1") is new


def test_a_closed_connection_is_not_reported_as_online():
    hub = WebSocketHub()
    live, _sock = connection("pi-1")
    hub.add(live)

    live.close()

    assert hub.is_online("pi-1") is False


def test_connections_are_listed_for_the_dashboard():
    hub = WebSocketHub()
    hub.add(connection("pi-1")[0])
    hub.add(connection("phone-2")[0])

    listed = {item["device_id"]: item for item in hub.connections()}

    assert set(listed) == {"pi-1", "phone-2"}
    assert listed["pi-1"]["kind"] == "node"
    assert listed["pi-1"]["idle_seconds"] >= 0


def test_close_all_disconnects_everything():
    hub = WebSocketHub()
    live, sock = connection("pi-1")
    hub.add(live)

    hub.close_all()

    assert sock.closed
    assert hub.connections() == []


def test_sending_on_a_closed_connection_raises_rather_than_silently_passing():
    from nekosuneai.ws_protocol import WebSocketError

    live, _sock = connection("pi-1")
    live.close()

    with pytest.raises(WebSocketError):
        live.send_json({"type": "reply"})
