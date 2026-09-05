"""VRChat's documented local OSC input and avatar parameter interface."""
from __future__ import annotations

import math
import re
import threading
import time


AXES = {"Vertical", "Horizontal", "LookHorizontal"}
BUTTONS = {"Jump", "Run", "UseRight", "UseLeft", "GrabRight", "GrabLeft", "DropRight", "DropLeft"}
SKILLS = {
    "vrchat.forward": ("Vertical", 1.0), "vrchat.back": ("Vertical", -1.0),
    "vrchat.left": ("Horizontal", -1.0), "vrchat.right": ("Horizontal", 1.0),
    "vrchat.look_left": ("LookHorizontal", -0.5), "vrchat.look_right": ("LookHorizontal", 0.5),
    "vrchat.jump": ("Jump", 1),
}


class VrchatOsc:
    def __init__(self, send_port=9000, receive_port=9001, gate=lambda: True, client=None):
        from pythonosc.udp_client import SimpleUDPClient
        self.client = client or SimpleUDPClient("127.0.0.1", int(send_port))
        self.receive_port = int(receive_port)
        self.gate = gate
        self.armed = threading.Event()
        self._cancel = threading.Event()
        self._lock = threading.RLock()
        self._action_lock = threading.Lock()
        self._server = None
        self._thread = None
        self._parameters = {}
        self._avatar = ""
        self._last_received = 0.0
        self._error = ""
        self._last_chat = 0.0

    def start(self):
        from pythonosc.dispatcher import Dispatcher
        from pythonosc.osc_server import BlockingOSCUDPServer
        dispatcher = Dispatcher()
        dispatcher.map("/avatar/change", self._receive)
        dispatcher.map("/avatar/parameters/*", self._receive)
        self._server = BlockingOSCUDPServer(("127.0.0.1", self.receive_port), dispatcher)
        self._thread = threading.Thread(target=self._server.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True)
        self._thread.start()

    def _receive(self, address, *values):
        if not values:
            return
        with self._lock:
            if address == "/avatar/change":
                self._avatar = str(values[0])[:100]
                self._parameters.clear()
            elif address.startswith("/avatar/parameters/"):
                name = address.rsplit("/", 1)[-1][:100]
                if len(self._parameters) < 128 or name in self._parameters:
                    value = values[0]
                    if isinstance(value, (bool, int, float)) and math.isfinite(value):
                        self._parameters[name] = value
            self._last_received = time.time()

    def status(self):
        with self._lock:
            return {"enabled": True, "armed": self.armed.is_set(),
                    "receiving": time.time() - self._last_received < 30,
                    "last_received_epoch": self._last_received, "avatar_id": self._avatar,
                    "parameters": dict(self._parameters), "error": self._error}

    def arm(self):
        if not self.gate():
            raise PermissionError("Select the VRChat profile and enable local game input first")
        self._cancel.clear()
        self.armed.set()

    def _check(self):
        if not self.armed.is_set() or not self.gate() or self._cancel.is_set():
            raise PermissionError("VRChat OSC control is not armed locally")

    def pulse(self, name, value=1, seconds=0.25):
        if name not in AXES | BUTTONS:
            raise ValueError("unsupported VRChat input")
        seconds, value = float(seconds), float(value)
        if not math.isfinite(seconds) or not 0.02 <= seconds <= 2 or not math.isfinite(value) or not -1 <= value <= 1:
            raise ValueError("OSC actions require a finite value from -1 to 1 and duration 0.02-2 seconds")
        if name in BUTTONS and value not in {0, 1}:
            raise ValueError("OSC buttons accept only 0 or 1")
        with self._action_lock:
            with self._lock:
                self._check()
                self.client.send_message("/input/" + name, float(value) if name in AXES else int(value))
            try:
                until = time.monotonic() + seconds
                while time.monotonic() < until:
                    if self._cancel.wait(min(0.02, max(0, until - time.monotonic()))) or not self.gate():
                        break
            finally:
                self.client.send_message("/input/" + name, 0.0 if name in AXES else 0)
        return {"ok": True, "input": name, "released": True}

    def avatar_parameter(self, name, value):
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", str(name)):
            raise ValueError("invalid avatar parameter name")
        if not isinstance(value, (bool, int, float)) or not math.isfinite(value) or abs(value) > 255:
            raise ValueError("avatar value must be a finite bool/int/float within -255..255")
        with self._lock:
            self._check()
            self.client.send_message("/avatar/parameters/" + name, value)
        return {"ok": True, "parameter": name, "value": value}

    def chatbox(self, text):
        text = str(text).strip()
        if not text or len(text) > 144:
            raise ValueError("VRChat chatbox accepts 1-144 characters")
        with self._lock:
            self._check()
            if time.monotonic() - self._last_chat < 2:
                raise RuntimeError("Wait two seconds between chatbox messages")
            self.client.send_message("/chatbox/input", [text, True, False])
            self._last_chat = time.monotonic()
        return {"ok": True, "sent": True}

    def stop_input(self):
        with self._lock:
            self.armed.clear()
            self._cancel.set()
            for name in AXES | BUTTONS:
                try:
                    self.client.send_message("/input/" + name, 0.0 if name in AXES else 0)
                except OSError as exc:
                    self._error = str(exc)

    def close(self):
        self.stop_input()
        if self._server:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._thread:
            self._thread.join(timeout=1)
