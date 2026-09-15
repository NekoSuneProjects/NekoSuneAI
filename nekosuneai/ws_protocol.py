"""Minimal RFC 6455 WebSocket framing, no dependencies.

The backend serves on stdlib `http.server.ThreadingHTTPServer`, which has no
WebSocket support and no place to plug an ASGI server in. It does give a
thread per connection and access to the raw socket, which is all a WebSocket
needs, so the handshake and frame codec live here rather than pulling in a
server framework for one endpoint.

Only what this protocol actually uses is implemented: text and binary data
frames, continuation frames, ping/pong, and close. No extensions, no
compression -- a negotiated `permessage-deflate` would have to be refused
anyway, and refusing is the default.

Why WebSockets at all: a device turn runs the whole pipeline (web search, the
LLM, TTS) and regularly outlives a reverse proxy's read timeout, which answers
the device 504 and discards a finished reply. A proxy applies its much longer
*idle* timeout to an upgraded connection instead, and ping/pong keeps even
that from firing, so the answer can take as long as it takes. It also lets the
backend push -- a reply, its audio, a command -- the moment it is ready,
rather than the device polling for it.
"""
from __future__ import annotations

import base64
import hashlib
import os
import socket
import struct
from typing import Any

# RFC 6455 section 1.3: the fixed string concatenated with the client's key
# before hashing, which is what proves to the client that the server
# understood the handshake rather than echoing bytes back.
_HANDSHAKE_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

OP_CONTINUATION = 0x0
OP_TEXT = 0x1
OP_BINARY = 0x2
OP_CLOSE = 0x8
OP_PING = 0x9
OP_PONG = 0xA

# A device sends transcripts and telemetry; it has no reason to send anything
# large, and an unbounded frame from a compromised node should not be able to
# exhaust the backend's memory.
MAX_FRAME_BYTES = 2 * 1024 * 1024
MAX_MESSAGE_BYTES = 8 * 1024 * 1024

CLOSE_NORMAL = 1000
CLOSE_GOING_AWAY = 1001
CLOSE_PROTOCOL_ERROR = 1002
CLOSE_TOO_LARGE = 1009
CLOSE_UNAUTHORIZED = 4401


class WebSocketError(Exception):
    """Protocol violation or transport failure; the connection must close."""


def accept_key(client_key: str) -> str:
    """The Sec-WebSocket-Accept value for a client's Sec-WebSocket-Key."""
    digest = hashlib.sha1((client_key.strip() + _HANDSHAKE_GUID).encode("ascii")).digest()
    return base64.b64encode(digest).decode("ascii")


def is_upgrade_request(headers: Any) -> bool:
    """Whether these request headers are asking to become a WebSocket.

    Both header values are lists in practice -- proxies routinely rewrite
    `Connection` to "keep-alive, Upgrade" -- so membership is tested rather
    than equality, which is what makes this work behind nginx and Cloudflare.
    """
    connection = str(headers.get("Connection", "")).lower()
    upgrade = str(headers.get("Upgrade", "")).lower()
    return "upgrade" in connection and upgrade == "websocket"


def handshake_response(headers: Any) -> bytes:
    """The raw 101 response for a valid upgrade request."""
    key = headers.get("Sec-Websocket-Key") or headers.get("Sec-WebSocket-Key")
    if not key:
        raise WebSocketError("upgrade request carried no Sec-WebSocket-Key")
    version = str(headers.get("Sec-Websocket-Version") or headers.get("Sec-WebSocket-Version") or "")
    if version.strip() != "13":
        raise WebSocketError(f"unsupported WebSocket version {version!r}")
    return (
        "HTTP/1.1 101 Switching Protocols\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Accept: {accept_key(str(key))}\r\n"
        "\r\n"
    ).encode("ascii")


def _mask(payload: bytes, key: bytes) -> bytes:
    return bytes(byte ^ key[index % 4] for index, byte in enumerate(payload))


def encode_frame(payload: bytes, opcode: int = OP_TEXT, *, mask: bool = False) -> bytes:
    """Build one complete, unfragmented frame.

    `mask` is for clients: RFC 6455 requires client-to-server frames to be
    masked and forbids it server-to-server.
    """
    header = bytearray()
    header.append(0x80 | (opcode & 0x0F))  # FIN set; this is never fragmented
    length = len(payload)
    mask_bit = 0x80 if mask else 0x00
    if length < 126:
        header.append(mask_bit | length)
    elif length < 65536:
        header.append(mask_bit | 126)
        header.extend(struct.pack("!H", length))
    else:
        header.append(mask_bit | 127)
        header.extend(struct.pack("!Q", length))
    if not mask:
        return bytes(header) + payload
    key = os.urandom(4)
    return bytes(header) + key + _mask(payload, key)


def _recv_exactly(sock: socket.socket, count: int) -> bytes:
    """Read exactly `count` bytes or fail; short reads are normal on sockets."""
    chunks: list[bytes] = []
    remaining = count
    while remaining > 0:
        chunk = sock.recv(remaining)
        if not chunk:
            raise WebSocketError("connection closed mid-frame")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def read_frame(sock: socket.socket) -> tuple[int, bytes, bool]:
    """Read one frame. Returns (opcode, payload, fin)."""
    first, second = _recv_exactly(sock, 2)
    opcode = first & 0x0F
    fin = bool(first & 0x80)
    masked = bool(second & 0x80)
    length = second & 0x7F

    if length == 126:
        (length,) = struct.unpack("!H", _recv_exactly(sock, 2))
    elif length == 127:
        (length,) = struct.unpack("!Q", _recv_exactly(sock, 8))
    if length > MAX_FRAME_BYTES:
        raise WebSocketError(f"frame of {length} bytes exceeds the {MAX_FRAME_BYTES} limit")

    key = _recv_exactly(sock, 4) if masked else b""
    payload = _recv_exactly(sock, length) if length else b""
    if masked:
        payload = _mask(payload, key)
    # A control frame must be short and must not be fragmented; letting one
    # through fragmented would desynchronise the message reassembly below.
    if opcode >= OP_CLOSE and (not fin or len(payload) > 125):
        raise WebSocketError("invalid control frame")
    return opcode, payload, fin


def read_message(sock: socket.socket, on_control: Any = None) -> tuple[int, bytes] | None:
    """Read one whole message, reassembling continuation frames.

    Control frames arriving mid-message are handed to `on_control` and do not
    interrupt reassembly, which is what keeps a ping during a long upload from
    corrupting it. Returns None once the peer closes.
    """
    opcode: int | None = None
    body = bytearray()
    while True:
        frame_opcode, payload, fin = read_frame(sock)
        if frame_opcode >= OP_CLOSE:
            if frame_opcode == OP_CLOSE:
                return None
            if on_control is not None:
                on_control(frame_opcode, payload)
            continue
        if frame_opcode != OP_CONTINUATION:
            opcode = frame_opcode
        elif opcode is None:
            raise WebSocketError("continuation frame with nothing to continue")
        body.extend(payload)
        if len(body) > MAX_MESSAGE_BYTES:
            raise WebSocketError("message exceeds the maximum size")
        if fin:
            return int(opcode or OP_TEXT), bytes(body)


def close_frame(code: int = CLOSE_NORMAL, reason: str = "") -> bytes:
    payload = struct.pack("!H", code) + reason.encode("utf-8")[:123]
    return encode_frame(payload, OP_CLOSE)
