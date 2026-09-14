"""The wake-word conversation loop (contract NODE-CONVERSE-01).

Detection used to dead-end at a logged transcript: the node heard you, wrote
the text to its command log, and said nothing back. These cover the path that
closed that gap -- transcript out, reply spoken, commands executed.
"""
from __future__ import annotations

import base64
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from nekosuneai.pi_proxy_agent import PiProxyAgent

REPLY_AUDIO = b"RIFF....WAVEfmt "


class _Backend(BaseHTTPRequestHandler):
    """Stub of the Docker backend's /api/nodes/* surface."""

    def log_message(self, *args):  # noqa: A002
        pass

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length) or b"{}")
        self.server.calls.append((self.path, payload, self.headers.get("X-Neko-Device-Token")))
        body = json.dumps(self.server.responses[self.path]).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture
def backend():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Backend)
    httpd.calls = []
    httpd.responses = {
        "/api/nodes/media/stt": {"ok": True, "text": "play lofi hip hop"},
        "/api/nodes/converse": {
            "ok": True,
            "reply": "Playing lofi hip hop.",
            "audio_base64": base64.b64encode(REPLY_AUDIO).decode("ascii"),
            "commands": [{"capability": "music.play", "arguments": {"query": "lofi hip hop"}}],
        },
    }
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield httpd
    finally:
        httpd.shutdown()


@pytest.fixture
def agent(backend, tmp_path):
    node = PiProxyAgent({
        "server_url": f"http://127.0.0.1:{backend.server_address[1]}",
        "node_id": "pi-test", "device_token": "tok-abc", "name": "Test Pi",
        "bluetooth_reconnect_enabled": False, "wake_word_enabled": False,
        "web_status_enabled": False, "alert_sounds_dir": str(tmp_path / "sounds"),
    })
    # Stand in for the hardware: a real mic, speaker and yt-dlp resolve.
    node.spoken, node.music = [], []
    node._record_wav = lambda seconds: b"FAKEWAV"
    node.player.play_wav_bytes = lambda raw: node.spoken.append(raw)
    node.music_player.play_url = lambda url: node.music.append(url)
    node._resolve_stream_url = lambda query: "http://stream.invalid/" + query.replace(" ", "+")
    return node


def test_wake_word_sends_transcript_and_speaks_the_reply(agent, backend):
    agent._on_wake_word_detected()

    assert [call[0] for call in backend.calls] == [
        "/api/nodes/media/stt", "/api/nodes/converse",
    ]
    stt, converse = backend.calls
    assert stt[2] == converse[2] == "tok-abc"      # device token on both hops
    assert converse[1]["text"] == "play lofi hip hop"
    assert converse[1]["node_id"] == "pi-test"
    assert agent.spoken == [REPLY_AUDIO]            # the reply is actually played


def test_music_command_from_the_reply_plays_on_this_node(agent):
    """The point of routing music here: yt-dlp resolves from a residential IP."""
    agent._on_wake_word_detected()
    assert agent.music == ["http://stream.invalid/lofi+hip+hop"]


def test_turn_is_recorded_for_the_dashboard(agent):
    agent._on_wake_word_detected()
    assert agent.last_reply == "Playing lofi hip hop."
    assert [dict(turn) for turn in agent.conversation] == [
        {"epoch": pytest.approx(time.time(), abs=30),
         "text": "play lofi hip hop", "reply": "Playing lofi hip hop."},
    ]
    status = agent.status()
    assert status["conversation"] and status["last_reply"] == "Playing lofi hip hop."


def test_missing_reply_audio_falls_back_to_the_local_voice(agent, backend):
    """A backend TTS failure must degrade to espeak-ng, not to silence."""
    backend.responses["/api/nodes/converse"] = {
        "ok": True, "reply": "The sky is blue.", "commands": [],
    }
    fallback = []
    agent._speak_local_fallback = fallback.append

    agent._on_wake_word_detected()

    assert fallback == ["The sky is blue."]
    assert agent.spoken == []


def test_silence_does_not_start_a_conversation_turn(agent, backend):
    backend.responses["/api/nodes/media/stt"] = {"ok": True, "text": "   "}

    agent._on_wake_word_detected()

    assert [call[0] for call in backend.calls] == ["/api/nodes/media/stt"]
    assert not agent.conversation


def test_converse_rejects_empty_text(agent):
    with pytest.raises(ValueError):
        agent.converse("")


def test_disabled_audio_blocks_a_wake_word_turn(agent, backend):
    """The local emergency stop has to hold against the node's own wake word."""
    agent.stop_all(disable=True)

    agent._on_wake_word_detected()

    assert backend.calls == []


def test_status_exposes_the_new_diagnostics(agent):
    status = agent.status()
    assert set(status["microphone"]) == {"alsa_device", "portaudio_name", "error"}
    assert set(status["alert_sounds"]) == {"dir", "error"}
    assert status["control_enabled"] is True
