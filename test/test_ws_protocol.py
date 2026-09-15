"""RFC 6455 handshake and framing.

Framing is easy to get subtly wrong in ways that only show up against a real
client, so the codec is exercised directly: length boundaries, masking,
fragmentation, control frames arriving mid-message, and the limits that stop a
compromised device exhausting the backend.
"""
from __future__ import annotations

import socket
import struct
import threading

import pytest

from nekosuneai.ws_protocol import (
    MAX_FRAME_BYTES,
    OP_BINARY,
    OP_CLOSE,
    OP_PING,
    OP_TEXT,
    WebSocketError,
    accept_key,
    encode_frame,
    handshake_response,
    is_upgrade_request,
    read_frame,
    read_message,
)


class FakeSocket:
    """Serves prepared bytes through the recv() contract, short reads included."""

    def __init__(self, data: bytes, chunk: int = 3):
        self.data = data
        self.chunk = chunk
        self.position = 0

    def recv(self, count: int) -> bytes:
        take = min(count, self.chunk, len(self.data) - self.position)
        if take <= 0:
            return b""
        out = self.data[self.position:self.position + take]
        self.position += take
        return out


def test_accept_key_matches_the_rfc_example():
    """RFC 6455 section 1.3's worked example."""
    assert accept_key("dGhlIHNhbXBsZSBub25jZQ==") == "s3pPLMBiTxaQ9kYGzzhZRbK+xOo="


def test_upgrade_is_detected_through_a_proxy_rewritten_header():
    """nginx and Cloudflare rewrite Connection to a list, which is the whole
    reason this is a membership test rather than an equality one."""
    assert is_upgrade_request({"Connection": "keep-alive, Upgrade", "Upgrade": "websocket"})
    assert is_upgrade_request({"Connection": "Upgrade", "Upgrade": "WebSocket"})
    assert not is_upgrade_request({"Connection": "keep-alive", "Upgrade": ""})
    assert not is_upgrade_request({})


def test_handshake_response_is_a_valid_101():
    response = handshake_response({
        "Sec-WebSocket-Key": "dGhlIHNhbXBsZSBub25jZQ==", "Sec-WebSocket-Version": "13",
    }).decode()

    assert response.startswith("HTTP/1.1 101 Switching Protocols\r\n")
    assert "Upgrade: websocket\r\n" in response
    assert "Sec-WebSocket-Accept: s3pPLMBiTxaQ9kYGzzhZRbK+xOo=\r\n" in response
    assert response.endswith("\r\n\r\n")


@pytest.mark.parametrize(
    ("headers", "match"),
    [
        ({"Sec-WebSocket-Version": "13"}, "Sec-WebSocket-Key"),
        ({"Sec-WebSocket-Key": "abc", "Sec-WebSocket-Version": "8"}, "unsupported"),
        ({"Sec-WebSocket-Key": "abc"}, "unsupported"),
    ],
)
def test_a_malformed_handshake_is_refused(headers, match):
    with pytest.raises(WebSocketError, match=match):
        handshake_response(headers)


@pytest.mark.parametrize("size", [0, 1, 125, 126, 127, 65535, 65536])
def test_every_payload_length_boundary_round_trips(size):
    """125/126 and 65535/65536 are where the length encoding changes width."""
    payload = b"x" * size

    opcode, body, fin = read_frame(FakeSocket(encode_frame(payload, OP_BINARY), chunk=7))

    assert (opcode, body, fin) == (OP_BINARY, payload, True)


def test_a_masked_client_frame_is_unmasked():
    payload = b"hello from a client"

    opcode, body, _fin = read_frame(FakeSocket(encode_frame(payload, OP_TEXT, mask=True)))

    assert (opcode, body) == (OP_TEXT, payload)


def test_server_frames_are_never_masked():
    """RFC 6455 forbids it server-to-client, and clients disconnect over it."""
    assert not encode_frame(b"data", OP_TEXT)[1] & 0x80
    assert encode_frame(b"data", OP_TEXT, mask=True)[1] & 0x80


def test_a_fragmented_message_is_reassembled():
    first = bytes([OP_TEXT, 5]) + b"hello"                 # FIN clear
    middle = bytes([0x00, 1]) + b" "                        # continuation
    last = bytes([0x80, 5]) + b"there"                      # FIN set

    opcode, body = read_message(FakeSocket(first + middle + last))

    assert (opcode, body) == (OP_TEXT, b"hello there")


def test_a_ping_during_a_fragmented_message_does_not_corrupt_it():
    """A keepalive arriving mid-upload must not desynchronise reassembly."""
    seen: list[tuple[int, bytes]] = []
    stream = (
        bytes([OP_TEXT, 5]) + b"hello"
        + encode_frame(b"", OP_PING)
        + bytes([0x80, 5]) + b"there"
    )

    opcode, body = read_message(FakeSocket(stream), on_control=lambda op, data: seen.append((op, data)))

    assert body == b"hellothere"
    assert seen == [(OP_PING, b"")]


def test_a_close_frame_ends_the_message_stream():
    assert read_message(FakeSocket(encode_frame(b"", OP_CLOSE))) is None


def test_an_oversized_frame_is_refused_before_it_is_read():
    """The length is rejected from the header, so the bytes are never buffered."""
    header = bytes([0x82, 127]) + struct.pack("!Q", MAX_FRAME_BYTES + 1)

    with pytest.raises(WebSocketError, match="exceeds"):
        read_frame(FakeSocket(header))


def test_a_fragmented_control_frame_is_refused():
    with pytest.raises(WebSocketError, match="control frame"):
        read_frame(FakeSocket(bytes([OP_PING, 0])))       # FIN clear on a ping


def test_an_oversized_control_frame_is_refused():
    with pytest.raises(WebSocketError, match="control frame"):
        read_frame(FakeSocket(bytes([0x80 | OP_PING, 126]) + struct.pack("!H", 200) + b"x" * 200))


def test_a_continuation_with_nothing_to_continue_is_refused():
    with pytest.raises(WebSocketError, match="continuation"):
        read_message(FakeSocket(bytes([0x80, 3]) + b"abc"))


def test_a_truncated_frame_is_an_error_not_a_hang():
    with pytest.raises(WebSocketError, match="closed mid-frame"):
        read_frame(FakeSocket(bytes([0x82, 10]) + b"only4"))


def test_a_real_socket_pair_round_trips():
    """The FakeSocket above models recv(); this proves it against a real one."""
    server, client = socket.socketpair()
    try:
        payload = b"y" * 70000        # past the 16-bit length boundary
        threading.Thread(
            target=lambda: client.sendall(encode_frame(payload, OP_BINARY, mask=True)),
            daemon=True,
        ).start()

        opcode, body = read_message(server)

        assert (opcode, len(body)) == (OP_BINARY, len(payload))
        assert body == payload
    finally:
        server.close()
        client.close()
