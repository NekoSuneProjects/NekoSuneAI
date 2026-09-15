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
        status = getattr(self.server, "status_code", 200)
        body = json.dumps(self.server.responses.get(self.path, {"error": "nope"})).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture
def backend():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Backend)
    httpd.calls = []
    httpd.status_code = 200
    httpd.responses = {
        "/api/nodes/media/stt": {"ok": True, "text": "play lofi hip hop"},
        "/api/nodes/heartbeat": {"ok": True},
        "/api/nodes/media/tts": {
            "ok": True,
            "audio_base64": base64.b64encode(REPLY_AUDIO).decode("ascii"),
            "content_type": "audio/wav",
        },
        "/api/nodes/poll": {"commands": []},
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
    node.spoken, node.played = [], []
    node._record_wav = lambda seconds: b"FAKEWAV"
    node.player.play_wav_bytes = lambda raw: node.spoken.append(raw)
    node.music._resolve = lambda query: ("http://stream.invalid/" + query.replace(" ", "+"), query)
    node.music._start_locked = lambda url: node.played.append(url)
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
    """The point of routing music here: yt-dlp resolves from a residential IP,
    and the speaker is in the owner's room rather than a datacenter."""
    agent._on_wake_word_detected()
    assert agent.played == ["http://stream.invalid/lofi+hip+hop"]


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


class TestRejectedPairing:
    """A 401 is not an outage.

    It used to fall into the generic heartbeat-failure counter, so a node with
    a stale device token announced "Connection to the main server has been
    lost. Running in offline mode." -- sending the owner to look at their
    network when the backend was up and the pairing was the problem.
    """

    def _agent(self, backend, tmp_path, status):
        from nekosuneai.pi_proxy_agent import PiProxyAgent

        node = PiProxyAgent({
            "server_url": f"http://127.0.0.1:{backend.server_address[1]}",
            "node_id": "pi-test", "device_token": "stale-token",
            "bluetooth_reconnect_enabled": False, "wake_word_enabled": False,
            "web_status_enabled": False, "alert_sounds_dir": str(tmp_path / "sounds"),
        })
        backend.status_code = status
        return node

    def test_rejected_token_raises_a_distinct_error(self, backend, tmp_path):
        from nekosuneai.pi_proxy_agent import NodeUnauthorizedError

        node = self._agent(backend, tmp_path, 401)

        with pytest.raises(NodeUnauthorizedError) as caught:
            node.heartbeat_once()
        # The message has to carry the actual remedy.
        assert "Re-pair the node" in str(caught.value)
        assert "pi-test" in str(caught.value)

    def test_forbidden_is_treated_the_same_way(self, backend, tmp_path):
        from nekosuneai.pi_proxy_agent import NodeUnauthorizedError

        node = self._agent(backend, tmp_path, 403)
        with pytest.raises(NodeUnauthorizedError):
            node.heartbeat_once()

    def test_a_server_error_is_still_an_ordinary_failure(self, backend, tmp_path):
        """500 really is "try again", and must keep the outage path."""
        from nekosuneai.pi_proxy_agent import NodeUnauthorizedError

        node = self._agent(backend, tmp_path, 500)
        with pytest.raises(Exception) as caught:
            node.heartbeat_once()
        assert not isinstance(caught.value, NodeUnauthorizedError)

    def test_the_dashboard_reports_a_rejected_pairing(self, backend, tmp_path):
        node = self._agent(backend, tmp_path, 401)
        assert node.status()["auth_error"] == ""

        node.auth_error = "rejected"
        assert node.status()["auth_error"] == "rejected"


class TestGatewayTimeoutSurvival:
    """A converse turn runs the whole backend pipeline and is long by nature.

    Anything in front of the backend that gives up first (nginx, Caddy,
    Cloudflare) answers 504 while the turn is still running, and the reply the
    backend had already produced was thrown away. It now leaves a copy on the
    command queue, which the poll collects seconds later.
    """

    def test_a_gateway_error_is_pending_not_a_failure(self, agent, backend):
        backend.status_code = 504
        backend.responses["/api/nodes/converse"] = {"error": "gateway timeout"}

        result = agent.converse("hello")

        assert result["pending"] is True
        assert "504" in result["reason"]
        assert agent.conversation[-1]["pending"] is True

    def test_a_client_timeout_is_also_pending(self, agent, monkeypatch):
        import requests

        def timeout(*args, **kwargs):
            raise requests.Timeout("read timed out")

        monkeypatch.setattr(agent.session, "post", timeout)

        assert agent.converse("hello")["pending"] is True

    def test_a_real_backend_error_still_raises(self, agent, backend):
        """400/500 from the backend itself is a genuine failure, not a wait."""
        backend.status_code = 400
        backend.responses["/api/nodes/converse"] = {"error": "text too long"}

        with pytest.raises(RuntimeError, match="text too long"):
            agent.converse("hello")

    def test_the_queued_reply_is_spoken_and_completes_the_turn(self, agent, backend):
        backend.status_code = 504
        backend.responses["/api/nodes/converse"] = {"error": "gateway timeout"}
        agent.converse("what is the weather")
        backend.status_code = 200

        agent._dispatch("conversation.reply", {
            "turn_id": "t1", "text": "It is raining.", "commands": [],
        })

        assert agent.spoken == [REPLY_AUDIO]       # fetched TTS and played it
        assert agent.last_reply == "It is raining."
        # The pending placeholder is completed, not duplicated.
        assert len(agent.conversation) == 1
        assert agent.conversation[-1]["reply"] == "It is raining."
        assert "pending" not in agent.conversation[-1]

    def test_the_queued_copy_of_an_inline_reply_is_not_spoken_twice(self, agent, backend):
        backend.responses["/api/nodes/converse"] = {
            "ok": True, "turn_id": "t7", "reply": "Hello there.",
            "audio_base64": base64.b64encode(REPLY_AUDIO).decode("ascii"), "commands": [],
        }
        agent.converse("hello")
        assert agent.spoken == [REPLY_AUDIO]

        result = agent._dispatch("conversation.reply", {"turn_id": "t7", "text": "Hello there."})

        assert result["duplicate"] is True
        assert agent.spoken == [REPLY_AUDIO]       # still once
        assert len(agent.conversation) == 1

    def test_a_queued_reply_runs_its_commands(self, agent):
        agent._dispatch("conversation.reply", {
            "turn_id": "t2", "text": "Playing lofi.",
            "commands": [{"capability": "music.play", "arguments": {"query": "lofi"}}],
        })

        assert agent.played == ["http://stream.invalid/lofi"]

    def test_a_queued_reply_falls_back_to_the_local_voice(self, agent, backend):
        """The same degradation the inline path has."""
        backend.responses["/api/nodes/media/tts"] = {"ok": True}      # no audio
        fallback = []
        agent._speak_local_fallback = fallback.append

        agent._dispatch("conversation.reply", {"turn_id": "t3", "text": "Offline answer."})

        assert fallback == ["Offline answer."]

    def test_the_node_advertises_the_capability(self, agent):
        assert agent.capabilities()["conversation.reply"] == {"kind": "write"}


class TestPairingFromTheDashboard:
    """Pairing a node from its own page instead of a terminal.

    The command-line flow works, but every additional Pi then needs a shell
    session and a hand-edited config. Opening the new node's dashboard and
    typing the code the backend just showed is the same operation without any
    of that.
    """

    @pytest.fixture
    def unpaired(self, backend, tmp_path):
        from nekosuneai.pi_proxy_agent import PiProxyAgent

        config_path = tmp_path / "pi-proxy-agent.json"
        config_path.write_text(json.dumps({
            "node_id": "pi-new", "name": "New Pi", "device_token": "",
            "wake_word_enabled": False, "bluetooth_reconnect_enabled": True,
        }), encoding="utf-8")
        node = PiProxyAgent({
            "server_url": "", "node_id": "pi-new", "name": "New Pi", "device_token": "",
            "bluetooth_reconnect_enabled": False, "wake_word_enabled": False,
            "web_status_enabled": False, "alert_sounds_dir": str(tmp_path / "sounds"),
        }, config_path=config_path)
        node.backend_port = backend.server_address[1]
        node.config_path_used = config_path
        backend.responses["/api/nodes/register"] = {"ok": True, "device_token": "fresh-token"}
        return node

    def test_a_node_can_start_unpaired(self, unpaired):
        assert unpaired.token == ""
        assert unpaired.status()["paired"] is False
        assert unpaired.status()["can_pair"] is True

    def test_pairing_stores_the_token_on_disk(self, unpaired):
        result = unpaired.pair_and_save(
            f"http://127.0.0.1:{unpaired.backend_port}", "pair-123", "ABCD-EFGH",
        )

        assert result["ok"] is True
        assert unpaired.token == "fresh-token"
        saved = json.loads(unpaired.config_path_used.read_text(encoding="utf-8"))
        assert saved["device_token"] == "fresh-token"
        assert saved["server_url"] == f"http://127.0.0.1:{unpaired.backend_port}"
        # Settings this agent did not touch survive the write.
        assert saved["node_id"] == "pi-new"
        assert saved["wake_word_enabled"] is False

    def test_pairing_releases_the_waiting_run_loop(self, unpaired):
        assert not unpaired._paired.is_set()

        unpaired.pair_and_save(f"http://127.0.0.1:{unpaired.backend_port}", "p", "c")

        assert unpaired._paired.is_set()

    @pytest.mark.parametrize(
        ("server", "pairing_id", "code"),
        [
            ("", "p", "c"),
            ("not-a-url", "p", "c"),
            ("http://x", "", "c"),
            ("http://x", "p", ""),
        ],
    )
    def test_bad_input_is_rejected_before_any_request(self, unpaired, backend, server, pairing_id, code):
        with pytest.raises(ValueError):
            unpaired.pair_and_save(server, pairing_id, code)
        assert not [c for c in backend.calls if c[0] == "/api/nodes/register"]

    def test_a_failed_pairing_leaves_the_previous_one_intact(self, unpaired, backend):
        """A mistyped code must not also lose a working pairing."""
        unpaired.token = "existing-token"
        unpaired.server = "https://old.example"
        backend.status_code = 403
        backend.responses["/api/nodes/register"] = {"error": "invalid or expired pairing code"}

        with pytest.raises(RuntimeError):
            unpaired.pair_and_save(f"http://127.0.0.1:{unpaired.backend_port}", "p", "c")

        assert unpaired.token == "existing-token"
        assert unpaired.server == "https://old.example"
