"""Windows-only paired game/vision/OBS node with a fail-closed input layer.

The Pi remains the planner. This agent captures only an approved game window,
sends compact observations, and executes named skills from a local profile.
There is deliberately no arbitrary key, shell, process, or desktop command.
"""
from __future__ import annotations

import argparse
import base64
import ctypes
import hashlib
import io
import json
import os
import platform
import re
import subprocess
import socket
import ssl
import sys
import threading
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

import requests
from ctypes import wintypes


SAFE_KEYS = {
    "w": 0x57, "a": 0x41, "s": 0x53, "d": 0x44, "e": 0x45, "f": 0x46,
    "space": 0x20, "escape": 0x1B, "enter": 0x0D, "tab": 0x09,
    "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
}
TRANSITION_WORDS = {"loading", "connecting", "respawn", "you died", "paused", "main menu"}


@dataclass
class GameProfile:
    game_id: str
    display_name: str
    executable_names: list[str] = field(default_factory=list)
    window_title_pattern: str = ""
    competitive_or_anticheat: bool = False
    allow_vision: bool = True
    allow_input: bool = False
    allow_obs: bool = True
    allow_twitch: bool = False
    capture_fps: float = 1.0
    capture_width: int = 960
    skills: dict[str, list[dict[str, Any]]] = field(default_factory=dict)

    @classmethod
    def load(cls, path: str | Path) -> "GameProfile":
        raw = json.loads(Path(path).read_text("utf-8"))
        known = {key: raw[key] for key in cls.__dataclass_fields__ if key in raw}
        profile = cls(**known)
        profile.capture_fps = max(0.1, min(float(profile.capture_fps), 10.0))
        profile.capture_width = max(320, min(int(profile.capture_width), 1920))
        if profile.competitive_or_anticheat:
            profile.allow_input = False
        if not profile.window_title_pattern:
            raise ValueError("window_title_pattern is required so desktop-wide control is impossible")
        for name, steps in profile.skills.items():
            if not re.fullmatch(r"[a-z0-9_.-]{1,64}", name) or not isinstance(steps, list):
                raise ValueError("skill names and steps are invalid")
            if len(steps) > 20:
                raise ValueError("a skill may contain at most 20 steps")
        return profile


class WindowsWindow:
    """Small ctypes wrapper; no broad desktop enumeration or remote shell."""

    @staticmethod
    def foreground() -> tuple[int, str]:
        if platform.system() != "Windows":
            return 0, ""
        user32 = ctypes.windll.user32
        handle = int(user32.GetForegroundWindow())
        length = int(user32.GetWindowTextLengthW(handle))
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(handle, buf, length + 1)
        return handle, buf.value

    @staticmethod
    def bounds(handle: int) -> tuple[int, int, int, int] | None:
        if platform.system() != "Windows" or not handle:
            return None
        rect = wintypes.RECT()
        if not ctypes.windll.user32.GetWindowRect(handle, ctypes.byref(rect)):
            return None
        if rect.right <= rect.left or rect.bottom <= rect.top:
            return None
        return rect.left, rect.top, rect.right, rect.bottom


class InputSafetyController:
    def __init__(
        self,
        profile: GameProfile,
        foreground: Callable[[], tuple[int, str]] = WindowsWindow.foreground,
        key_event: Callable[[int, bool], None] | None = None,
    ) -> None:
        self.profile = profile
        self.foreground = foreground
        self.key_event = key_event or self._windows_key_event
        self.disabled = threading.Event()
        self._held: set[int] = set()
        self._lock = threading.RLock()

    @staticmethod
    def _windows_key_event(code: int, down: bool) -> None:
        if platform.system() != "Windows":
            raise RuntimeError("game input is available only on Windows")
        ctypes.windll.user32.keybd_event(code, 0, 0 if down else 0x0002, 0)

    def approved_window(self) -> bool:
        _handle, title = self.foreground()
        try:
            return bool(re.search(self.profile.window_title_pattern, title, re.I))
        except re.error:
            return False

    def stop_all(self, disable: bool = False) -> None:
        if disable:
            self.disabled.set()
        with self._lock:
            for code in list(self._held):
                try:
                    self.key_event(code, False)
                except Exception:
                    pass
            self._held.clear()

    def enable(self) -> None:
        self.stop_all()
        self.disabled.clear()

    def run_skill(self, name: str) -> dict[str, Any]:
        if self.disabled.is_set():
            raise PermissionError("AI game input is locally disabled")
        if self.profile.competitive_or_anticheat:
            raise PermissionError("automated input is disabled for competitive/anti-cheat profiles")
        if not self.profile.allow_input:
            raise PermissionError("input is disabled in this game profile")
        if not self.approved_window():
            self.stop_all()
            raise PermissionError("the approved game window is not in the foreground")
        steps = self.profile.skills.get(str(name))
        if not steps:
            raise ValueError("skill is not allowlisted in this game profile")
        deadline = time.monotonic() + 10.0
        completed = 0
        try:
            for step in steps:
                if self.disabled.is_set() or time.monotonic() >= deadline or not self.approved_window():
                    raise RuntimeError("skill stopped by timeout, emergency stop, or window change")
                key = str(step.get("key", "")).lower()
                if key not in SAFE_KEYS:
                    raise ValueError(f"key is not allowlisted: {key}")
                duration = max(0.02, min(float(step.get("seconds", 0.1)), 2.0))
                code = SAFE_KEYS[key]
                with self._lock:
                    self.key_event(code, True)
                    self._held.add(code)
                time.sleep(duration)
                with self._lock:
                    self.key_event(code, False)
                    self._held.discard(code)
                completed += 1
        finally:
            self.stop_all()
        return {"ok": True, "skill": name, "steps": completed}


class EmergencyHotkey:
    """Local Ctrl+Alt+F12 kill switch; never depends on the Pi/network."""
    def __init__(self, controller: InputSafetyController) -> None:
        self.controller = controller
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if platform.system() != "Windows" or (self._thread and self._thread.is_alive()): return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="game-input-emergency-hotkey")
        self._thread.start()

    def _loop(self) -> None:
        was_down = False
        while not self._stop.wait(0.05):
            user32 = ctypes.windll.user32
            down = all(user32.GetAsyncKeyState(code) & 0x8000 for code in (0x11, 0x12, 0x7B))
            if down and not was_down:
                self.controller.stop_all(disable=True)
            was_down = down

    def stop(self) -> None:
        self._stop.set()


class WindowVision:
    def __init__(self, profile: GameProfile, foreground: Callable[[], tuple[int, str]] = WindowsWindow.foreground) -> None:
        self.profile = profile
        self.foreground = foreground
        self.last_capture = 0.0
        self.last_hash = ""
        self.memory: deque[dict[str, Any]] = deque(maxlen=20)

    def capture(self, detailed: bool = False) -> dict[str, Any]:
        if not self.profile.allow_vision:
            return {"ok": False, "reason": "vision disabled in profile"}
        handle, title = self.foreground()
        if not re.search(self.profile.window_title_pattern, title, re.I):
            return {"ok": False, "reason": "approved game window is not foreground"}
        interval = 1.0 / self.profile.capture_fps
        if not detailed and time.monotonic() - self.last_capture < interval:
            return self.memory[-1] if self.memory else {"ok": False, "reason": "capture rate limited"}
        bounds = WindowsWindow.bounds(handle)
        if bounds is None:
            return {"ok": False, "reason": "window bounds unavailable"}
        try:
            from PIL import ImageGrab
            image = ImageGrab.grab(bbox=bounds)
            if image.width > self.profile.capture_width:
                ratio = self.profile.capture_width / image.width
                image = image.resize((self.profile.capture_width, max(1, int(image.height * ratio))))
            gray = image.convert("L").resize((32, 18))
            digest = hashlib.sha256(gray.tobytes()).hexdigest()[:16]
            scene_changed = bool(self.last_hash and digest != self.last_hash)
            self.last_hash, self.last_capture = digest, time.monotonic()
            text = ""
            try:
                import pytesseract
                text = " ".join(pytesseract.image_to_string(image).split())[:800]
            except Exception:
                pass
            transition = next((word for word in TRANSITION_WORDS if word in text.lower()), "")
            result: dict[str, Any] = {
                "ok": True, "window_title": title[:120], "width": image.width, "height": image.height,
                "scene_hash": digest, "scene_changed": scene_changed, "ocr": text,
                "transition": transition, "input_safe": not bool(transition), "epoch": time.time(),
            }
            if detailed:
                buf = io.BytesIO()
                image.save(buf, "JPEG", quality=55, optimize=True)
                encoded = base64.b64encode(buf.getvalue()).decode("ascii")
                if len(encoded) <= 48_000:
                    result["screenshot_jpeg_base64"] = encoded
                else:
                    result["screenshot_omitted"] = "compressed screenshot exceeded heartbeat limit"
            self.memory.append({key: value for key, value in result.items() if key != "screenshot_jpeg_base64"})
            return result
        except Exception as exc:
            return {"ok": False, "reason": f"capture unavailable: {exc}"}


class ObsController:
    def __init__(self, host: str, port: int, password: str) -> None:
        self.host, self.port, self.password = host, int(port), password
        self.client = None

    def connect(self) -> None:
        try:
            import obsws_python as obs
        except ImportError as exc:
            raise RuntimeError("install requirements-windows-agent.txt for OBS control") from exc
        self.client = obs.ReqClient(host=self.host, port=self.port, password=self.password, timeout=3)

    def _client(self):
        if self.client is None:
            self.connect()
        return self.client

    def status(self) -> dict[str, Any]:
        client = self._client()
        stream, record = client.get_stream_status(), client.get_record_status()
        return {
            "connected": True, "streaming": bool(stream.output_active), "recording": bool(record.output_active),
            "stream_timecode": getattr(stream, "output_timecode", ""),
            "dropped_frames": getattr(stream, "output_skipped_frames", 0),
        }

    def command(self, action: str, value: Any = None, confirmed: bool = False) -> dict[str, Any]:
        client = self._client()
        if action in {"stream.start", "stream.stop"} and not confirmed:
            raise PermissionError("starting/stopping a live stream requires confirmation")
        if action == "scene": client.set_current_program_scene(str(value))
        elif action == "stream.start": client.start_stream()
        elif action == "stream.stop": client.stop_stream()
        elif action == "record.start": client.start_record()
        elif action == "record.stop": client.stop_record()
        elif action == "replay.save": client.save_replay_buffer()
        else: raise ValueError("unsupported OBS action")
        return {"ok": True, "action": action, "value": value}


class TwitchIrcClient:
    """Minimal Twitch IRC client; credentials and socket remain on Windows."""
    PRIVMSG = re.compile(r"^(?:@(?P<tags>[^ ]+) )?:(?P<user>[^!]+)![^ ]+ PRIVMSG #[^ ]+ :(?P<text>.*)$")

    def __init__(self, login: str, oauth_token: str, channel: str) -> None:
        self.login = login.strip().lower()
        self.oauth_token = oauth_token.strip()
        self.channel = channel.strip().lstrip("#").lower()
        self.socket: socket.socket | None = None
        self.messages: deque[dict[str, Any]] = deque(maxlen=100)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._send_times: deque[float] = deque(maxlen=20)

    @classmethod
    def parse_line(cls, line: str) -> dict[str, Any] | None:
        match = cls.PRIVMSG.match(line.rstrip("\r\n"))
        if not match:
            return None
        tags = {}
        for part in (match.group("tags") or "").split(";"):
            key, _, value = part.partition("=")
            tags[key] = value
        return {
            "id": tags.get("id") or hashlib.sha256(line.encode()).hexdigest()[:16],
            "user": tags.get("display-name") or match.group("user"),
            "text": match.group("text")[:500], "highlighted": tags.get("msg-id") == "highlighted-message",
            "epoch": time.time(),
        }

    def start(self) -> None:
        if self._thread and self._thread.is_alive(): return
        if not self.login or not self.oauth_token or not self.channel: return
        raw = socket.create_connection(("irc.chat.twitch.tv", 6697), timeout=10)
        self.socket = ssl.create_default_context().wrap_socket(raw, server_hostname="irc.chat.twitch.tv")
        self.socket.sendall(
            f"PASS {self.oauth_token}\r\nNICK {self.login}\r\nCAP REQ :twitch.tv/tags twitch.tv/commands\r\nJOIN #{self.channel}\r\n".encode()
        )
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="twitch-irc")
        self._thread.start()

    def _loop(self) -> None:
        buffer = ""
        try:
            while not self._stop.is_set() and self.socket is not None:
                chunk = self.socket.recv(8192)
                if not chunk: break
                buffer += chunk.decode("utf-8", "replace")
                while "\r\n" in buffer:
                    line, buffer = buffer.split("\r\n", 1)
                    if line.startswith("PING"):
                        self.socket.sendall(("PONG" + line[4:] + "\r\n").encode()); continue
                    parsed = self.parse_line(line)
                    if parsed: self.messages.append(parsed)
        finally:
            self.stop()

    def drain(self) -> list[dict[str, Any]]:
        rows = list(self.messages); self.messages.clear(); return rows

    def send(self, text: str) -> None:
        clean = " ".join(str(text).split())[:450]
        if not clean or self.socket is None: raise RuntimeError("Twitch IRC is not connected")
        now = time.time()
        while self._send_times and now - self._send_times[0] > 30: self._send_times.popleft()
        if len(self._send_times) >= 18: raise RuntimeError("Twitch chat send rate limit reached")
        self.socket.sendall(f"PRIVMSG #{self.channel} :{clean}\r\n".encode())
        self._send_times.append(now)

    def stop(self) -> None:
        self._stop.set()
        sock, self.socket = self.socket, None
        if sock:
            try: sock.close()
            except Exception: pass


class WindowsGamingAgent:
    def __init__(self, config: dict[str, Any], profile: GameProfile) -> None:
        self.config, self.profile = config, profile
        self.server = str(config["server_url"]).rstrip("/")
        self.node_id = str(config.get("node_id") or platform.node() or "windows-gaming")
        self.token = str(config.get("device_token") or "")
        self.verify_tls = bool(config.get("verify_tls", True))
        self.session = requests.Session()
        self.input = InputSafetyController(profile)
        self.emergency_hotkey = EmergencyHotkey(self.input)
        self.vision = WindowVision(profile)
        self.obs = ObsController(
            str(config.get("obs_host", "127.0.0.1")), int(config.get("obs_port", 4455)),
            str(config.get("obs_password", "")),
        )
        self._stop = threading.Event()
        self._last_command = 0
        self._last_result: dict[str, Any] = {}
        self.twitch = None
        if profile.allow_twitch and config.get("twitch_login") and config.get("twitch_oauth_token") and config.get("twitch_channel"):
            self.twitch = TwitchIrcClient(
                str(config["twitch_login"]), str(config["twitch_oauth_token"]), str(config["twitch_channel"]),
            )

    def capabilities(self) -> dict[str, dict[str, str]]:
        caps = {
            "game.status": {"kind": "read"}, "game.observe": {"kind": "read"},
            "game.capture": {"kind": "write"}, "game.input.stop": {"kind": "write"},
        }
        if self.profile.allow_input:
            caps["game.skill"] = {"kind": "write"}
        if self.profile.allow_obs:
            for name in ("obs.status", "obs.stream.status", "obs.scene", "obs.stream.start", "obs.stream.stop", "obs.record", "obs.replay.save"):
                caps[name] = {"kind": "read" if name in {"obs.status", "obs.stream.status"} else "write"}
        if self.profile.allow_twitch:
            caps.update({"twitch.chat.read": {"kind": "read"}, "twitch.chat.send": {"kind": "write"}})
        return caps

    def pair(self, pairing_id: str, pairing_code: str) -> str:
        response = self.session.post(
            self.server + "/api/nodes/register",
            json={
                "pairing_id": pairing_id, "pairing_code": pairing_code, "node_id": self.node_id,
                "name": str(self.config.get("name", "Windows Gaming Node")), "node_type": "windows-gaming",
                "capabilities": self.capabilities(),
            }, timeout=10, verify=self.verify_tls,
        )
        response.raise_for_status()
        self.token = str(response.json()["device_token"])
        return self.token

    def _headers(self) -> dict[str, str]:
        return {"X-Neko-Device-Token": self.token}

    def _telemetry(self) -> dict[str, Any]:
        _handle, title = WindowsWindow.foreground()
        state: dict[str, Any] = {
            "game_id": self.profile.game_id, "active_window": title[:120],
            "input_disabled": self.input.disabled.is_set(), "observation": self.vision.capture(),
            "last_command_result": self._last_result, "skills": sorted(self.profile.skills),
        }
        try:
            import psutil
            processes = {str(proc.info.get("name") or "").casefold() for proc in psutil.process_iter(["name"])}
            expected = {name.casefold() for name in self.profile.executable_names}
            state.update({
                "cpu_percent": psutil.cpu_percent(), "memory_percent": psutil.virtual_memory().percent,
                "game_running": bool(expected & processes) if expected else bool(re.search(self.profile.window_title_pattern, title, re.I)),
            })
        except Exception:
            pass
        try:
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,memory.total", "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=2, check=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            gpu, used, total = [float(value.strip()) for value in result.stdout.splitlines()[0].split(",")[:3]]
            state.update({"gpu_percent": gpu, "gpu_memory_used_mb": used, "gpu_memory_total_mb": total})
        except Exception:
            pass
        if self.profile.allow_obs:
            try: state["obs"] = self.obs.status()
            except Exception as exc: state["obs"] = {"connected": False, "error": str(exc)[:200]}
        if self.twitch is not None:
            state["twitch_chat"] = self.twitch.drain()
        return state

    def _execute(self, command: dict[str, Any]) -> dict[str, Any]:
        capability = str(command.get("capability", ""))
        args = dict(command.get("arguments") or {})
        confirmed = bool(command.get("confirmed"))
        if capability == "game.input.stop":
            self.input.stop_all(disable=True); return {"ok": True, "input_disabled": True}
        if capability == "game.skill":
            return self.input.run_skill(str(args.get("name", "")))
        if capability == "game.capture":
            return self.vision.capture(detailed=True)
        if capability == "obs.scene":
            return self.obs.command("scene", args.get("scene"), confirmed)
        if capability.startswith("obs.stream."):
            return self.obs.command(capability.removeprefix("obs."), confirmed=confirmed)
        if capability == "obs.record":
            return self.obs.command("record.start" if args.get("active", True) else "record.stop", confirmed=confirmed)
        if capability == "obs.replay.save":
            return self.obs.command("replay.save", confirmed=confirmed)
        if capability == "twitch.chat.send":
            if self.twitch is None: raise RuntimeError("Twitch chat is not configured")
            self.twitch.send(str(args.get("text", ""))); return {"ok": True, "sent": True}
        raise ValueError("command capability is not handled locally")

    def heartbeat_once(self) -> dict[str, Any]:
        response = self.session.post(
            self.server + "/api/nodes/heartbeat", headers=self._headers(), verify=self.verify_tls, timeout=10,
            json={"node_id": self.node_id, "state": self._telemetry(), "ack_command_id": self._last_command or None},
        )
        response.raise_for_status()
        # A requested screenshot is delivered in one heartbeat only. Compact
        # action metadata remains available, but the image does not linger.
        self._last_result.pop("screenshot_jpeg_base64", None)
        poll = self.session.post(
            self.server + "/api/nodes/poll", headers=self._headers(), verify=self.verify_tls, timeout=30,
            json={"node_id": self.node_id, "after": self._last_command, "wait_seconds": 10},
        )
        poll.raise_for_status()
        for command in poll.json().get("commands", []):
            try: self._last_result = self._execute(command)
            except Exception as exc: self._last_result = {"ok": False, "error": str(exc)[:300]}
            self._last_command = max(self._last_command, int(command.get("id", 0)))
        return response.json()

    def run(self) -> None:
        if not self.token:
            raise RuntimeError("pair the agent first and store device_token in its config")
        try:
            self.emergency_hotkey.start()
            if self.twitch is not None: self.twitch.start()
            while not self._stop.is_set():
                try: self.heartbeat_once()
                except Exception:
                    self.input.stop_all()
                    if self._stop.wait(3): break
        finally:
            self.emergency_hotkey.stop()
            if self.twitch is not None: self.twitch.stop()
            self.input.stop_all(disable=True)


def install_startup(config_path: Path, profile_path: Path) -> Path:
    if platform.system() != "Windows":
        raise RuntimeError("startup installation is available only on Windows")
    startup = Path(os.environ["APPDATA"]) / "Microsoft/Windows/Start Menu/Programs/Startup"
    target = startup / "NekoSuneAI-Windows-Gaming-Agent.cmd"
    target.write_text(
        f'@echo off\r\n"{sys.executable}" -m nekosuneai.windows_gaming_agent --config "{config_path}" --profile "{profile_path}"\r\n',
        "utf-8",
    )
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description="NekoSuneAI paired Windows Gaming Agent")
    parser.add_argument("--config", required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--pairing-id", default="")
    parser.add_argument("--pairing-code", default="")
    parser.add_argument("--install-startup", action="store_true")
    args = parser.parse_args()
    config_path, profile_path = Path(args.config).resolve(), Path(args.profile).resolve()
    config = json.loads(config_path.read_text("utf-8"))
    profile = GameProfile.load(profile_path)
    if args.install_startup:
        print(install_startup(config_path, profile_path)); return
    agent = WindowsGamingAgent(config, profile)
    if args.pairing_id and args.pairing_code:
        config["device_token"] = agent.pair(args.pairing_id, args.pairing_code)
        config_path.write_text(json.dumps(config, indent=2), "utf-8")
        print("Paired successfully; the device token was saved locally.")
    agent.run()


if __name__ == "__main__":
    main()
