"""Paired Android gameplay worker for NekoSuneAI Main.

Runs beside an ADB-enabled emulator/device. No remote shell or generic ADB
command execution is exposed. All input is bounded and package-scoped.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import signal
import threading
import time
from pathlib import Path

import requests

from .device import AndroidDevice
from .game_detection import detect_foreground

PACKAGE_RE = re.compile(r"^[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)+$")
CAPABILITIES = {
    "game.devices": {"kind": "read"},
    "game.detect": {"kind": "read"},
    "game.profile": {"kind": "read"},
    "game.disney.profile": {"kind": "read"},
    "game.disney.moves": {"kind": "read"},
    "game.disney.plan": {"kind": "read"},
    "game.navigation.plan": {"kind": "read"},
    "game.observe": {"kind": "read"},
    "game.action": {"kind": "write"},
    "game.session.start": {"kind": "write"},
    "game.session.stop": {"kind": "write"},
    "game.input.stop": {"kind": "write"},
    "game.session.pause": {"kind": "write"},
    "game.session.resume": {"kind": "write"},
}


class AndroidGameWorker:
    def __init__(self, server: str, node_id: str, token: str = "",
                 allowed_packages=(), device=None, http=None, state_file=None):
        self.server = server.rstrip("/")
        if not (self.server.startswith("https://") or
                self.server.startswith("http://127.0.0.1:") or
                self.server.startswith("http://localhost:")):
            raise ValueError("Use HTTPS for remote Main connections")
        self.node_id = node_id
        self.token = token
        self.allowed = set(allowed_packages)
        if not self.allowed or any(not PACKAGE_RE.fullmatch(p) for p in self.allowed):
            raise ValueError("Set explicit valid --allow-package values")
        self.device = device or AndroidDevice()
        self.http = http or requests.Session()
        self.stop_event = threading.Event()
        self.session_id = ""
        self.package = ""
        self.ack_id = 0
        self.last_result = {}
        self.state_file = Path(state_file) if state_file else None
        if self.state_file and self.state_file.exists():
            saved = json.loads(self.state_file.read_text(encoding="utf-8"))
            if saved.get("node_id") != self.node_id:
                raise ValueError("Node ID mismatch in persistent state")
            self.ack_id = max(0, int(saved.get("ack_id", 0)))
            self.last_result = saved.get("last_result") or {}
        self.last_contact = time.monotonic()
        self.session_deadline = 0.0
        self.max_actions = 100
        self.actions_used = 0
        self.paused = False
        self.autoplay = None

    def enable_autoplay(self, model_url, model_name, config_file="config.json"):
        from .paired_autoplay import PairedAutoplay
        self.autoplay = PairedAutoplay(self, model_url, model_name, config_file)

    def capabilities(self):
        manifest = dict(CAPABILITIES)
        if self.autoplay:
            manifest.update({"game.autoplay.start": {"kind": "write"},
                             "game.autoplay.status": {"kind": "read"}})
        return manifest

    def _persist(self):
        if self.state_file is None:
            return
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        temp = self.state_file.with_name(self.state_file.name + ".tmp")
        temp.write_text(json.dumps({
            "node_id": self.node_id, "ack_id": self.ack_id,
            "last_result": self.last_result,
        }), encoding="utf-8")
        os.replace(temp, self.state_file)
        if os.name != "nt":
            os.chmod(self.state_file, 0o600)

    def _disarm(self):
        if self.autoplay:
            self.autoplay.stop()
        self.session_id = ""
        self.package = ""
        self.session_deadline = 0.0
        self.actions_used = 0
        self.paused = False

    def headers(self):
        return {"X-Neko-Device-Token": self.token}

    def _post(self, path, payload, timeout=15, authenticated=True):
        response = self.http.post(
            self.server + path,
            json=payload,
            headers=self.headers() if authenticated else {},
            timeout=timeout,
        )
        response.raise_for_status()
        return response.json()

    def pair(self, pairing_id, pairing_code):
        result = self._post("/api/nodes/register", {
            "pairing_id": pairing_id, "pairing_code": pairing_code,
            "node_id": self.node_id, "name": "Android Gameplay",
            "node_type": "android-gaming", "capabilities": self.capabilities(),
        }, authenticated=False)
        self.token = result["device_token"]
        self._disarm()
        self.ack_id = 0
        self.last_result = {}
        self._persist()
        return self.token

    def _active(self):
        if not self.session_id or not self.package:
            raise PermissionError("No approved active game session")
        if time.monotonic() >= self.session_deadline or self.actions_used >= self.max_actions:
            self._disarm()
            raise PermissionError("Session time or action budget expired")
        if self.device.foreground_package() != self.package:
            self._disarm()
            raise PermissionError("Game lost foreground; stopped session")

    def execute(self, capability, args):
        if capability in ("game.input.stop", "game.session.stop"):
            self._disarm()
            return {"stopped": True}
        if capability in ("game.session.pause", "game.session.resume"):
            self._active()
            if args.get("session_id") != self.session_id:
                raise PermissionError("Pause/resume session mismatch")
            self.paused = capability == "game.session.pause"
            if self.autoplay:
                self.autoplay.pause() if self.paused else self.autoplay.resume()
            return {"paused": self.paused, "session_id": self.session_id}
        if capability == "game.autoplay.status":
            return self.autoplay.status() if self.autoplay else {"status": "disabled"}
        if capability == "game.autoplay.start":
            if not self.autoplay:
                raise PermissionError("Autoplay is disabled locally")
            self._active()
            if args.get("session_id") != self.session_id:
                raise PermissionError("Autoplay session mismatch")
            expiry = args.get("expires_epoch")
            if not isinstance(expiry, (int, float)) or not time.time() < expiry <= time.time() + 30:
                raise PermissionError("Autoplay start is expired or missing deadline")
            return self.autoplay.start(args.get("goal", ""))
        if capability == "game.disney.profile":
            if self.device.foreground_package() != "com.superplaystudios.disneysolitairedreams":
                raise PermissionError("Disney Solitaire must be foreground")
            from .disney_solitaire import profile
            return profile()
        if capability == "game.disney.plan":
            self._active()
            if self.package != "com.superplaystudios.disneysolitairedreams":
                raise PermissionError("Disney Solitaire session required")
            if args.get("session_id") != self.session_id:
                raise PermissionError("Disney Solitaire planning session mismatch")
            from .disney_solitaire import propose_action
            frame = self.device.screenshot()
            height, width = frame.shape[:2]
            # All recognition inputs must be supplied by the vision pipeline.
            # Never infer highlights or free entitlement from package alone.
            scene = str(args.get("scene") or "unknown")
            exposed = args.get("exposed_cards", [])
            if not isinstance(exposed, list) or len(exposed) > 60:
                raise ValueError("Invalid observed card list")
            buttons = args.get("close_buttons", [])
            if not isinstance(buttons, list) or len(buttons) > 12:
                raise ValueError("Invalid observed close buttons")
            return {"scene": scene, "proposal": propose_action(
                scene, foundation_rank=args.get("foundation_rank"),
                exposed_cards=exposed, screen_width=width,
                screen_height=height, close_buttons=buttons,
                extra_cards_button=args.get("extra_cards_button"),
                wild_button=args.get("wild_button")),
                "execution": "proposal_only", "fresh_vision_required": True}
        if capability == "game.disney.moves":
            self._active()
            if self.package != "com.superplaystudios.disneysolitairedreams":
                raise PermissionError("Disney Solitaire session required")
            from .disney_solitaire import legal_moves
            cards = args.get("exposed_cards", [])
            if not isinstance(cards, list) or len(cards) > 60:
                raise ValueError("Expected at most 60 observed cards")
            return {"moves": legal_moves(args.get("foundation_rank"), cards),
                    "warning": "Proposals only; cards must be confirmed against fresh vision"}
        if capability == "game.profile":
            if self.device.foreground_package() != "com.moonactive.coinmaster":
                raise PermissionError("Original Coin Master must be foreground")
            from .original_coinmaster import scene_help
            return scene_help()
        if capability == "game.navigation.plan":
            self._active()
            if self.package != "com.moonactive.coinmaster":
                raise PermissionError("Original Coin Master session required")
            from .original_coinmaster import navigation_plan
            frame = self.device.screenshot()
            height, width = frame.shape[:2]
            return navigation_plan(str(args.get("current_scene", "unknown")),
                                   str(args.get("destination", "")), width, height)
        if capability == "game.detect":
            return detect_foreground(self.device, self.allowed)
        if capability == "game.devices":
            return {"packages": sorted(set(self.device.list_packages()) & self.allowed)}
        if capability == "game.session.start":
            package = str(args.get("game_id") or "")
            sid = str(args.get("session_id") or "")
            if not sid or len(sid) > 128 or package not in self.allowed:
                raise PermissionError("Session or game not approved")
            expiry = args.get("expires_epoch")
            if not isinstance(expiry, (int, float)) or not time.time() < expiry <= time.time() + 30:
                raise PermissionError("Expired or missing session-start deadline")
            if package not in self.device.list_packages(third_party_only=False):
                raise ValueError("Package is not installed")
            if self.session_id:
                raise RuntimeError("Stop the active session before starting another")
            if self.device.foreground_package() != package:
                raise PermissionError("Open the approved game locally first")
            duration = int(args.get("duration_seconds", 300))
            budget = int(args.get("max_actions", 100))
            if not 1 <= duration <= 3600 or not 1 <= budget <= 500:
                raise ValueError("Invalid duration or action budget")
            self.session_id, self.package = sid, package
            self.session_deadline = time.monotonic() + duration
            self.max_actions = budget
            self.actions_used = 0
            self.paused = False
            return {"session_id": sid, "game_id": package, "started": True}
        if capability == "game.observe":
            self._active()
            result = {"session_id": self.session_id, "game_id": self.package,
                      "foreground_package": self.device.foreground_package(),
                      "screenshot_available": True}
            if args.get("analyze") is True:
                import cv2
                frame = self.device.screenshot()
                height, width = frame.shape[:2]
                scale = min(1.0, 640 / max(height, width))
                if scale < 1:
                    frame = cv2.resize(frame, (max(1, int(width * scale)),
                                               max(1, int(height * scale))))
                ok, encoded = cv2.imencode(".jpg", frame,
                                           [cv2.IMWRITE_JPEG_QUALITY, 60])
                if not ok or len(encoded) > 350000:
                    raise ValueError("Screenshot exceeds image budget")
                result["vision"] = self._post("/api/nodes/media/vision", {
                    "node_id": self.node_id,
                    "image_base64": base64.b64encode(encoded.tobytes()).decode("ascii"),
                }, timeout=90)
            return result
        if capability != "game.action":
            raise PermissionError("Unsupported capability")
        if self.paused:
            raise PermissionError("Session paused")
        if self.autoplay and self.autoplay.status()["running"]:
            raise PermissionError("Manual action blocked during autonomous gameplay")
        self._active()
        if args.get("session_id") != self.session_id or args.get("game_id") != self.package:
            raise PermissionError("Action not bound to active session/game")
        # Do not execute stale actions queued during a network interruption.
        # Stops remain unconditional so they can always disarm input.
        expires = args.get("expires_epoch")
        if expires is None:
            raise PermissionError("Game action requires an expiration timestamp")
        if not isinstance(expires, (int, float)) or not time.time() < expires <= time.time() + 30:
            raise PermissionError("Game action expired or expiry too far ahead")
        action = args.get("action")
        if not isinstance(action, dict):
            raise ValueError("Missing typed action")
        kind = str(action.get("type", ""))
        if kind == "tap":
            frame = self.device.screenshot()
            h, w = frame.shape[:2]
            x, y = int(action["x"]), int(action["y"])
            if not (0 <= x < w and 0 <= y < h):
                raise ValueError("Tap is outside screenshot bounds")
            self.device.tap(x, y)
        elif kind == "swipe":
            frame = self.device.screenshot()
            h, w = frame.shape[:2]
            coords = [int(action[k]) for k in ("x1", "y1", "x2", "y2")]
            x1, y1, x2, y2 = coords
            if not (0 <= x1 < w and 0 <= x2 < w and 0 <= y1 < h and 0 <= y2 < h):
                raise ValueError("Swipe outside screenshot bounds")
            duration = int(action.get("duration_ms", 350))
            if not 50 <= duration <= 1500:
                raise ValueError("Unsafe swipe duration")
            self.device.swipe(*coords, duration)
        elif kind == "back":
            self.device.back()
        else:
            raise PermissionError("Action type not supported by paired worker")
        self.actions_used += 1
        return {"executed": kind, "session_id": self.session_id, "actions_used": self.actions_used}

    def once(self):
        if not self.token:
            raise RuntimeError("Pair before polling")
        if self.session_id:
            if (time.monotonic() >= self.session_deadline or
                    self.actions_used >= self.max_actions or
                    self.device.foreground_package() != self.package):
                self._disarm()
        state = {
            "platform": "android", "game_running": bool(self.session_id),
            "game_id": self.package, "session_id": self.session_id,
            "input_disabled": not bool(self.session_id) or self.paused,
            "paused": self.paused,
            "actions_used": self.actions_used,
            "max_actions": self.max_actions,
            "last_command_result": self.last_result,
            "autoplay": self.autoplay.status() if self.autoplay else {"status": "disabled"},
            "detected_game": detect_foreground(self.device, self.allowed),
        }
        self._post("/api/nodes/heartbeat", {
            "node_id": self.node_id, "state": state,
            "capabilities": self.capabilities(), "ack_command_id": self.ack_id or None,
        })
        response = self._post("/api/nodes/poll", {
            "node_id": self.node_id, "after": self.ack_id, "wait_seconds": 5,
        }, timeout=15)
        self.last_contact = time.monotonic()
        for command in response.get("commands", []):
            cid = int(command["id"])
            if cid <= self.ack_id:
                continue
            # Reject stale queued input after a reconnection. A fresh session
            # requires an explicit owner request; expired commands fail closed.
            # Write-ahead delivery receipt: prefer a skipped uncertain action
            # to double-executing a tap after a process crash.
            self.ack_id = cid
            self.last_result = {"command_id": cid, "ok": False,
                                "error": "execution outcome uncertain"}
            try:
                self._persist()
            except OSError:
                self._disarm()
                raise
            try:
                result = self.execute(command.get("capability"),
                                      command.get("arguments") or {})
                self.last_result = {"command_id": cid, "ok": True, "result": result}
            except Exception as exc:
                self.last_result = {"command_id": cid, "ok": False,
                                    "error": str(exc)[:240]}
            try:
                self._persist()
            except OSError:
                self._disarm()
                raise
        return self.last_result

    def serve(self):
        while not self.stop_event.is_set():
            try:
                self.once()
            except (requests.RequestException, OSError, ValueError, RuntimeError):
                self._disarm()
                self.stop_event.wait(3)

    def stop(self):
        self._disarm()
        self.stop_event.set()


def main():
    parser = argparse.ArgumentParser(description="Paired NekoSuneAI Android gaming node")
    parser.add_argument("--server", required=True)
    parser.add_argument("--node-id", default="android-gameplay-1")
    parser.add_argument("--allow-package", action="append", required=True)
    parser.add_argument("--device-serial", default="")
    parser.add_argument("--token-file", default=".android-game-node-token")
    parser.add_argument("--state-file", default=".android-game-node-state.json")
    parser.add_argument("--autoplay-model-url", default="")
    parser.add_argument("--autoplay-model", default="")
    parser.add_argument("--autoplay-config", default="config.json")
    parser.add_argument("--pairing-id")
    parser.add_argument("--pairing-code")
    args = parser.parse_args()
    token_path = Path(args.token_file)
    token = token_path.read_text().strip() if token_path.exists() else ""
    worker = AndroidGameWorker(args.server, args.node_id, token,
                               args.allow_package, AndroidDevice(serial=args.device_serial),
                               state_file=args.state_file)
    if args.autoplay_model_url and args.autoplay_model:
        worker.enable_autoplay(args.autoplay_model_url, args.autoplay_model,
                               args.autoplay_config)
    if args.pairing_id and args.pairing_code:
        token = worker.pair(args.pairing_id, args.pairing_code)
        fd = os.open(token_path, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as handle:
            handle.write(token + "\n")
    if not worker.token:
        parser.error("Pair using --pairing-id/--pairing-code or supply --token-file")
    signal.signal(signal.SIGTERM, lambda *_: worker.stop())
    signal.signal(signal.SIGINT, lambda *_: worker.stop())
    worker.serve()


if __name__ == "__main__":
    main()
