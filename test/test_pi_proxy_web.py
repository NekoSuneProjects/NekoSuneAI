"""The local dashboard's control surface.

The page used to be strictly read-only. These pin down that each control maps
onto a capability the agent already implements, and that the two ways of
turning controls off actually turn them off.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

import pytest

from nekosuneai.pi_proxy_web import PiProxyWebStatusServer


class FakeBluetooth:
    def reconnect_now(self):
        return True, "Alexa reconnected."


class FakeMusic:
    def __init__(self):
        self.paused = False

    def status(self):
        return {"paused": self.paused, "playing": not self.paused, "title": "Lofi", "volume": 70}


class FakeAgent:
    def __init__(self):
        self.calls = []
        self.bt = FakeBluetooth()
        self.music = FakeMusic()
        self.disabled = False

    def status(self):
        return {
            "epoch": time.time(), "node_id": "pi-1", "name": "Living Room",
            "paired": True, "input_disabled": self.disabled, "control_enabled": True,
            "bluetooth": {"connected": True, "ready": True, "name": "Alexa"},
            "music": self.music.status(),
            "microphone": {"alsa_device": "plughw:2,0", "portaudio_name": "Xbox NUI Audio", "error": ""},
            "alert_sounds": {"dir": "/opt/sounds", "error": ""},
            "wake_word": {"enabled": True, "running": True, "model": "hey_jarvis"},
            "conversation": [], "recent_commands": [],
        }

    def microphones(self):
        return [{"alsa_device": "plughw:2,0", "name": "Xbox NUI Audio", "is_kinect": True}]

    def converse(self, text, speak=True):
        self.calls.append(("converse", text))
        return {"reply": "Sure."}

    def listen_and_converse(self):
        self.calls.append(("listen",))
        return {"ok": True, "text": "hello"}

    def _dispatch(self, capability, arguments):
        self.calls.append((capability, arguments))
        return {"ok": True, "volume": arguments.get("percent"), "title": "Next track"}

    def set_capture_device(self, device):
        self.calls.append(("mic", device))
        return device

    def stop_all(self, disable=False):
        self.disabled = disable
        self.calls.append(("stop_all", disable))

    def enable(self):
        self.disabled = False
        self.calls.append(("enable",))


@pytest.fixture
def served():
    """Start the dashboard on an ephemeral port and yield (agent, post, get)."""
    servers = []

    def _start(**kwargs):
        agent = FakeAgent()
        server = PiProxyWebStatusServer(agent, port=0, **kwargs)
        server.start()
        servers.append(server)
        port = server._httpd.server_address[1]

        def post(body, pin=None):
            request = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/control",
                data=json.dumps(body).encode(),
                headers={"Content-Type": "application/json"}, method="POST",
            )
            if pin:
                request.add_header("X-Neko-Pi-Pin", pin)
            try:
                with urllib.request.urlopen(request, timeout=5) as response:
                    return response.status, json.loads(response.read())
            except urllib.error.HTTPError as exc:
                return exc.code, json.loads(exc.read())

        def get(path="/api/status"):
            with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as response:
                return response.status, response.read()

        return agent, post, get

    yield _start
    for server in servers:
        server.stop()


def test_page_and_status_are_served(served):
    _agent, _post, get = served()

    code, body = get("/")
    assert code == 200 and b"Talk to Neko" in body

    code, raw = get()
    assert json.loads(raw)["microphones"][0]["alsa_device"] == "plughw:2,0"


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ({"action": "ask", "text": "why is the sky blue"}, ("converse", "why is the sky blue")),
        ({"action": "listen"}, ("listen",)),
        ({"action": "music_play", "query": "lofi"}, ("music.play", {"query": "lofi"})),
        ({"action": "music_stop"}, ("music.stop", {})),
        ({"action": "music_skip"}, ("music.skip", {"previous": False})),
        ({"action": "music_skip", "previous": True}, ("music.skip", {"previous": True})),
        ({"action": "music_volume", "percent": 40}, ("music.volume", {"percent": 40})),
        ({"action": "set_microphone", "alsa_device": "plughw:2,0"}, ("mic", "plughw:2,0")),
        ({"action": "stop_all"}, ("stop_all", True)),
        ({"action": "enable"}, ("enable",)),
    ],
)
def test_each_control_reaches_the_matching_capability(served, body, expected):
    agent, post, _get = served()

    code, result = post(body)

    assert code == 200 and result["ok"]
    assert agent.calls[-1] == expected


def test_pause_button_follows_what_the_player_is_actually_doing(served):
    """One button for pause and resume, so the page cannot drift out of step."""
    agent, post, _get = served()

    post({"action": "music_pause"})
    assert agent.calls[-1][0] == "music.pause"

    agent.music.paused = True
    post({"action": "music_pause"})
    assert agent.calls[-1][0] == "music.resume"


def test_bluetooth_reconnect_reports_the_watchdog_message(served):
    _agent, post, _get = served()
    assert post({"action": "bluetooth_reconnect"})[1]["message"] == "Alexa reconnected."


@pytest.mark.parametrize(
    "body",
    [{"action": "nope"}, {"action": "ask", "text": ""}, {"action": "music_play", "query": ""}],
)
def test_bad_requests_are_rejected(served, body):
    agent, post, _get = served()
    assert post(body)[0] == 400
    assert agent.calls == []


def test_read_only_mode_blocks_every_control(served):
    agent, post, _get = served(control_enabled=False)

    code, result = post({"action": "music_stop"})

    assert code == 403 and agent.calls == []
    assert "disabled" in result["error"]


def test_pin_is_required_and_checked_when_set(served):
    agent, post, _get = served(control_pin="1234")

    assert post({"action": "music_stop"})[0] == 401
    assert post({"action": "music_stop"}, pin="9999")[0] == 401
    assert agent.calls == []

    assert post({"action": "music_stop"}, pin="1234")[0] == 200
    assert agent.calls[-1][0] == "music.stop"
