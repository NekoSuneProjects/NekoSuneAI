"""Fail-closed line-oriented client for locally launched HIDMaestro .NET sidecar."""
import json
import os
import subprocess
import threading
from pathlib import Path

BUTTONS = {"a","b","x","y","left_shoulder","right_shoulder","back","start",
           "left_thumb","right_thumb","dpad_up","dpad_down","dpad_left","dpad_right"}
AXES = {"left_x","left_y","right_x","right_y","left_trigger","right_trigger"}

class HIDMaestroController:
    def __init__(self, backend):
        if backend not in ("xbox360","dualshock4"):
            raise ValueError("unsupported HIDMaestro gamepad profile")
        path = Path(os.environ.get("NEKOSUNE_HIDMAESTRO_BRIDGE",
                                 "tools/hidmaestro-bridge/bin/Release/net10.0-windows/HIDMaestroBridge.exe"))
        if not path.is_file():
            raise RuntimeError("HIDMaestro bridge not installed. Build tools/hidmaestro-bridge; install driver on your PC with consent.")
        self._lock = threading.RLock()
        self.process = subprocess.Popen([str(path), backend], stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                        text=True, bufsize=1)
        self._command("ping")

    def _command(self, op, **data):
        with self._lock:
            if self.process.poll() is not None:
                raise RuntimeError("HIDMaestro bridge terminated")
            self.process.stdin.write(json.dumps({"op": op, **data}) + "\n")
            self.process.stdin.flush()
            response = self.process.stdout.readline()
            if not response:
                raise RuntimeError("HIDMaestro bridge disconnected")
            reply = json.loads(response)
            if reply.get("ok") is not True:
                raise RuntimeError("HIDMaestro rejected command: " + str(reply.get("error","unknown")))
            return reply

    def button(self, name, down):
        if name not in BUTTONS or type(down) is not bool:
            raise ValueError("invalid HIDMaestro button")
        self._command("button", name=name, down=down)

    def axis(self, name, value):
        if name not in AXES or isinstance(value, bool) or not -1 <= float(value) <= 1:
            raise ValueError("invalid HIDMaestro axis")
        self._command("axis", name=name, value=float(value))

    def reset(self):
        self._command("reset")

    def close(self):
        try:
            self.reset()
        finally:
            self.process.terminate()
