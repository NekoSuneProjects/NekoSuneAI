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
import queue
import re
import subprocess
import socket
import ssl
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import requests
from ctypes import wintypes

from .game_skills import GameSkillLibrary, SkillLearningStore, validate_skill_step
from .node_media_client import NodeMediaClient


SAFE_KEYS = {
    # Full letter row so every game's real single-key bindings (sprint, crouch,
    # reload, flashlight, journal, quicksave, hotbar, etc.) can be named
    # directly instead of games improvising unrelated substitute keys.
    "a": 0x41, "b": 0x42, "c": 0x43, "d": 0x44, "e": 0x45, "f": 0x46,
    "g": 0x47, "h": 0x48, "i": 0x49, "j": 0x4A, "k": 0x4B, "l": 0x4C,
    "m": 0x4D, "n": 0x4E, "o": 0x4F, "p": 0x50, "q": 0x51, "r": 0x52,
    "s": 0x53, "t": 0x54, "u": 0x55, "v": 0x56, "w": 0x57, "x": 0x58,
    "y": 0x59, "z": 0x5A,
    "shift": 0x10, "ctrl": 0x11, "alt": 0x12,
    "0": 0x30, "1": 0x31, "2": 0x32, "3": 0x33, "4": 0x34,
    "5": 0x35, "6": 0x36, "7": 0x37, "8": 0x38, "9": 0x39,
    "space": 0x20, "escape": 0x1B, "enter": 0x0D, "tab": 0x09, "backspace": 0x08,
    "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
    # Individually-pressable extras. There is no modifier+key combo support
    # (steps press and release one key at a time), so OS-level shortcuts such
    # as Alt+F4 or Alt+Tab cannot be formed even though the base keys exist.
    "capslock": 0x14, "home": 0x24, "end": 0x23, "pageup": 0x21, "pagedown": 0x22,
    "insert": 0x2D, "delete": 0x2E,
    # f12 is deliberately excluded: it is reserved for the local
    # Ctrl+Alt+F12 emergency stop hotkey and must never be an assignable skill.
    "f1": 0x70, "f2": 0x71, "f3": 0x72, "f4": 0x73, "f5": 0x74, "f6": 0x75,
    "f7": 0x76, "f8": 0x77, "f9": 0x78, "f10": 0x79, "f11": 0x7A,
    "grave": 0xC0, "minus": 0xBD, "equals": 0xBB,
    "leftbracket": 0xDB, "rightbracket": 0xDD, "backslash": 0xDC,
    "semicolon": 0xBA, "quote": 0xDE, "comma": 0xBC, "period": 0xBE, "slash": 0xBF,
}
SAFE_MOUSE_BUTTONS = {"left", "right", "middle"}
SAFE_CONTROLLER_BUTTONS = {
    "a", "b", "x", "y", "left_shoulder", "right_shoulder", "back", "start",
    "left_thumb", "right_thumb", "dpad_up", "dpad_down", "dpad_left", "dpad_right",
}
SAFE_CONTROLLER_AXES = {"left_x", "left_y", "right_x", "right_y", "left_trigger", "right_trigger"}
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
    allow_keyboard: bool = True
    allow_mouse: bool = False
    allow_controller: bool = False
    allow_obs: bool = True
    allow_twitch: bool = False
    platform: str = "windows"
    input_backend: str = "keyboard_mouse"
    multiplayer_policy: str = "single_player"
    automation_permitted: bool = True
    realtime_enabled: bool = True
    realtime_max_intent_seconds: float = 8.0
    realtime_repeat_delay: float = 0.04
    learning_enabled: bool = True
    capture_fps: float = 1.0
    capture_width: int = 960
    skills: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    skill_metadata: dict[str, dict[str, Any]] = field(default_factory=dict)
    guide_summary: str = ""

    @classmethod
    def load(cls, path: str | Path) -> "GameProfile":
        raw = json.loads(Path(path).read_text("utf-8"))
        return cls.from_mapping(raw)

    @classmethod
    def from_mapping(cls, raw: dict[str, Any]) -> "GameProfile":
        known = {key: raw[key] for key in cls.__dataclass_fields__ if key in raw}
        profile = cls(**known)
        profile.capture_fps = max(0.1, min(float(profile.capture_fps), 10.0))
        profile.capture_width = max(320, min(int(profile.capture_width), 1920))
        profile.realtime_max_intent_seconds = max(0.25, min(float(profile.realtime_max_intent_seconds), 8.0))
        profile.realtime_repeat_delay = max(0.02, min(float(profile.realtime_repeat_delay), 1.0))
        if profile.multiplayer_policy not in {"single_player", "private_server", "permitted_multiplayer", "prohibited"}:
            raise ValueError("invalid multiplayer_policy")
        if profile.competitive_or_anticheat or profile.multiplayer_policy == "prohibited":
            profile.allow_input = False
        if profile.multiplayer_policy != "single_player" and not profile.automation_permitted:
            profile.allow_input = False
        if profile.input_backend not in {"keyboard_mouse", "xbox360", "dualshock4"}:
            raise ValueError("input_backend must be keyboard_mouse, xbox360, or dualshock4")
        if not profile.window_title_pattern:
            raise ValueError("window_title_pattern is required so desktop-wide control is impossible")
        for name, steps in profile.skills.items():
            if not re.fullmatch(r"[a-z0-9_.-]{1,64}", name) or not isinstance(steps, list):
                raise ValueError("skill names and steps are invalid")
            if len(steps) > 20:
                raise ValueError("a profile skill may contain at most 20 steps")
            for step in steps:
                if not isinstance(step, dict):
                    raise ValueError("skill steps must be objects")
                validate_skill_step(step)
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


class VirtualGamepad:
    """Optional ViGEm-backed controller used by PC and Remote Play profiles."""

    def __init__(self, backend: str) -> None:
        try:
            import vgamepad as vg
        except ImportError as exc:
            raise RuntimeError("install requirements-windows-agent.txt for virtual controller support") from exc
        self.vg = vg
        self.backend = backend
        self.pad = vg.VDS4Gamepad() if backend == "dualshock4" else vg.VX360Gamepad()

    def button(self, name: str, down: bool) -> None:
        vg = self.vg
        if self.backend == "dualshock4":
            names = {
                "a": "DS4_BUTTON_CROSS", "b": "DS4_BUTTON_CIRCLE", "x": "DS4_BUTTON_SQUARE",
                "y": "DS4_BUTTON_TRIANGLE", "left_shoulder": "DS4_BUTTON_SHOULDER_LEFT",
                "right_shoulder": "DS4_BUTTON_SHOULDER_RIGHT", "back": "DS4_BUTTON_SHARE",
                "start": "DS4_BUTTON_OPTIONS", "left_thumb": "DS4_BUTTON_THUMB_LEFT",
                "right_thumb": "DS4_BUTTON_THUMB_RIGHT",
            }
            if name.startswith("dpad_"):
                directions = {
                    "dpad_up": "DS4_DPAD_DIRECTIONS.DS4_BUTTON_DPAD_NORTH",
                    "dpad_down": "DS4_DPAD_DIRECTIONS.DS4_BUTTON_DPAD_SOUTH",
                    "dpad_left": "DS4_DPAD_DIRECTIONS.DS4_BUTTON_DPAD_WEST",
                    "dpad_right": "DS4_DPAD_DIRECTIONS.DS4_BUTTON_DPAD_EAST",
                }
                enum_name, member = directions[name].split(".")
                direction = (
                    getattr(getattr(vg, enum_name), member) if down
                    else vg.DS4_DPAD_DIRECTIONS.DS4_BUTTON_DPAD_NONE
                )
                self.pad.directional_pad(direction=direction)
            else:
                value = getattr(vg.DS4_BUTTONS, names[name])
                (self.pad.press_button if down else self.pad.release_button)(button=value)
        else:
            names = {
                "a": "XUSB_GAMEPAD_A", "b": "XUSB_GAMEPAD_B", "x": "XUSB_GAMEPAD_X", "y": "XUSB_GAMEPAD_Y",
                "left_shoulder": "XUSB_GAMEPAD_LEFT_SHOULDER", "right_shoulder": "XUSB_GAMEPAD_RIGHT_SHOULDER",
                "back": "XUSB_GAMEPAD_BACK", "start": "XUSB_GAMEPAD_START",
                "left_thumb": "XUSB_GAMEPAD_LEFT_THUMB", "right_thumb": "XUSB_GAMEPAD_RIGHT_THUMB",
                "dpad_up": "XUSB_GAMEPAD_DPAD_UP", "dpad_down": "XUSB_GAMEPAD_DPAD_DOWN",
                "dpad_left": "XUSB_GAMEPAD_DPAD_LEFT", "dpad_right": "XUSB_GAMEPAD_DPAD_RIGHT",
            }
            value = getattr(vg.XUSB_BUTTON, names[name])
            (self.pad.press_button if down else self.pad.release_button)(button=value)
        self.pad.update()

    def axis(self, name: str, value: float) -> None:
        value = max(-1.0, min(float(value), 1.0))
        if name == "left_x": self.pad.left_joystick_float(x_value_float=value, y_value_float=0.0)
        elif name == "left_y": self.pad.left_joystick_float(x_value_float=0.0, y_value_float=value)
        elif name == "right_x": self.pad.right_joystick_float(x_value_float=value, y_value_float=0.0)
        elif name == "right_y": self.pad.right_joystick_float(x_value_float=0.0, y_value_float=value)
        elif name == "left_trigger": self.pad.left_trigger_float(value_float=max(0.0, value))
        elif name == "right_trigger": self.pad.right_trigger_float(value_float=max(0.0, value))
        self.pad.update()

    def reset(self) -> None:
        self.pad.reset()
        self.pad.update()


class InputSafetyController:
    def __init__(
        self,
        profile: GameProfile,
        foreground: Callable[[], tuple[int, str]] = WindowsWindow.foreground,
        key_event: Callable[[int, bool], None] | None = None,
        mouse_event: Callable[[str, bool, int, int], None] | None = None,
        gamepad: Any | None = None,
    ) -> None:
        self.profile = profile
        self.foreground = foreground
        self.key_event = key_event or self._windows_key_event
        self.mouse_event = mouse_event or self._windows_mouse_event
        self.gamepad = gamepad
        self.disabled = threading.Event()
        self._held: set[int] = set()
        self._held_mouse: set[str] = set()
        self._held_controller: set[str] = set()
        self._lock = threading.RLock()
        self._run_lock = threading.RLock()

    @staticmethod
    def _windows_key_event(code: int, down: bool) -> None:
        if platform.system() != "Windows":
            raise RuntimeError("game input is available only on Windows")
        ctypes.windll.user32.keybd_event(code, 0, 0 if down else 0x0002, 0)

    @staticmethod
    def _windows_mouse_event(button: str, down: bool, dx: int = 0, dy: int = 0) -> None:
        if platform.system() != "Windows":
            raise RuntimeError("game input is available only on Windows")
        flags = {
            ("left", True): 0x0002, ("left", False): 0x0004,
            ("right", True): 0x0008, ("right", False): 0x0010,
            ("middle", True): 0x0020, ("middle", False): 0x0040,
        }
        flag = 0x0001 if button == "move" else flags[(button, down)]
        ctypes.windll.user32.mouse_event(flag, int(dx), int(dy), 0, 0)

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
            for button in list(self._held_mouse):
                try: self.mouse_event(button, False, 0, 0)
                except Exception: pass
            self._held_mouse.clear()
            if self.gamepad is not None:
                try: self.gamepad.reset()
                except Exception: pass
            self._held_controller.clear()

    def enable(self) -> None:
        self.stop_all()
        self.disabled.clear()

    def run_skill(self, name: str) -> dict[str, Any]:
        with self._run_lock:
            return self._run_skill_locked(name)

    def _run_skill_locked(self, name: str) -> dict[str, Any]:
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
                duration = max(0.02, min(float(step.get("seconds", 0.1)), 2.0))
                if key:
                    if not self.profile.allow_keyboard or key not in SAFE_KEYS:
                        raise ValueError(f"key is not allowlisted: {key}")
                    code = SAFE_KEYS[key]
                    with self._lock: self.key_event(code, True); self._held.add(code)
                    time.sleep(duration)
                    with self._lock: self.key_event(code, False); self._held.discard(code)
                elif "mouse_button" in step:
                    button = str(step["mouse_button"]).lower()
                    if not self.profile.allow_mouse or button not in SAFE_MOUSE_BUTTONS:
                        raise ValueError(f"mouse button is not allowlisted: {button}")
                    with self._lock: self.mouse_event(button, True, 0, 0); self._held_mouse.add(button)
                    time.sleep(duration)
                    with self._lock: self.mouse_event(button, False, 0, 0); self._held_mouse.discard(button)
                elif "mouse_move" in step:
                    if not self.profile.allow_mouse:
                        raise ValueError("mouse movement is not allowed in this profile")
                    move = dict(step.get("mouse_move") or {})
                    dx = max(-250, min(int(move.get("x", 0)), 250))
                    dy = max(-250, min(int(move.get("y", 0)), 250))
                    self.mouse_event("move", True, dx, dy)
                    time.sleep(duration)
                elif "button" in step:
                    button = str(step["button"]).lower()
                    if not self.profile.allow_controller or button not in SAFE_CONTROLLER_BUTTONS or self.gamepad is None:
                        raise ValueError(f"controller button is not allowlisted: {button}")
                    with self._lock: self.gamepad.button(button, True); self._held_controller.add(button)
                    time.sleep(duration)
                    with self._lock: self.gamepad.button(button, False); self._held_controller.discard(button)
                elif "axis" in step:
                    axis = str(step["axis"]).lower()
                    if not self.profile.allow_controller or axis not in SAFE_CONTROLLER_AXES or self.gamepad is None:
                        raise ValueError(f"controller axis is not allowlisted: {axis}")
                    self.gamepad.axis(axis, float(step.get("value", 0.0)))
                    time.sleep(duration)
                    self.gamepad.axis(axis, 0.0)
                elif step.get("wait") is not None:
                    time.sleep(duration)
                else:
                    raise ValueError("skill step does not contain an approved input")
                completed += 1
        finally:
            self.stop_all()
        return {"ok": True, "skill": name, "steps": completed}


class RealtimeActionLoop:
    """Continue a short approved intent locally while the Pi plans the next one."""

    def __init__(
        self,
        profile: GameProfile,
        controller: InputSafetyController,
        safe_to_act: Callable[[], bool],
        record_result: Callable[[str, bool, float, str], Any],
    ) -> None:
        self.profile = profile
        self.controller = controller
        self.safe_to_act = safe_to_act
        self.record_result = record_result
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._skill = ""
        self._expires = 0.0
        self._generation = 0
        self.last_result: dict[str, Any] = {}

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="realtime-game-actions")
        self._thread.start()

    def set_intent(self, skill: str, seconds: float) -> dict[str, Any]:
        if not self.profile.realtime_enabled:
            raise PermissionError("real-time intents are disabled in this game profile")
        if skill not in self.profile.skills:
            raise ValueError("real-time intent is not an approved skill")
        if not bool((self.profile.skill_metadata.get(skill) or {}).get("realtime", False)):
            raise PermissionError("this skill is not marked safe for real-time repetition")
        ttl = max(0.25, min(float(seconds), self.profile.realtime_max_intent_seconds))
        with self._lock:
            self._skill, self._expires = skill, time.monotonic() + ttl
            self._generation += 1
        self._wake.set()
        return {"ok": True, "intent": skill, "expires_in_seconds": ttl, "generation": self._generation}

    def cancel(self, disable: bool = False) -> None:
        with self._lock:
            self._skill, self._expires = "", 0.0
            self._generation += 1
        self.controller.stop_all(disable=disable)
        self._wake.set()

    def status(self) -> dict[str, Any]:
        with self._lock:
            remaining = max(0.0, self._expires - time.monotonic())
            return {
                "active": bool(self._skill and remaining > 0), "skill": self._skill,
                "remaining_seconds": round(remaining, 2), "generation": self._generation,
                "last_result": dict(self.last_result),
            }

    def _loop(self) -> None:
        while not self._stop.is_set():
            with self._lock:
                skill, expires, generation = self._skill, self._expires, self._generation
            if not skill or time.monotonic() >= expires:
                if skill:
                    self.cancel()
                self._wake.wait(0.25); self._wake.clear(); continue
            if not self.safe_to_act():
                self.controller.stop_all()
                self._wake.wait(0.1); self._wake.clear(); continue
            started = time.monotonic()
            try:
                result = self.controller.run_skill(skill)
                elapsed = (time.monotonic() - started) * 1000
                self.record_result(skill, True, elapsed, "")
                self.last_result = {**result, "duration_ms": round(elapsed, 2), "generation": generation}
            except Exception as exc:
                elapsed = (time.monotonic() - started) * 1000
                self.record_result(skill, False, elapsed, str(exc))
                self.last_result = {"ok": False, "skill": skill, "error": str(exc)[:240], "generation": generation}
                self.cancel(disable=isinstance(exc, PermissionError))
            self._wake.wait(self.profile.realtime_repeat_delay); self._wake.clear()

    def stop(self) -> None:
        self._stop.set()
        self.cancel()
        self._wake.set()


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
    def __init__(self, profile: GameProfile, foreground: Callable[[], tuple[int, str]] = WindowsWindow.foreground, config=None) -> None:
        self.profile = profile
        self.config = config or {}
        self.foreground = foreground
        self.last_capture = 0.0
        self.last_hash = ""
        self.memory: deque[dict[str, Any]] = deque(maxlen=20)
        self._lock = threading.RLock()

    def capture(self, detailed: bool = False, image_limit: int = 48_000) -> dict[str, Any]:
        with self._lock:
            return self._capture_unlocked(detailed, image_limit)

    def _capture_unlocked(self, detailed: bool = False, image_limit: int = 48_000) -> dict[str, Any]:
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
            ocr_error = ""
            try:
                import pytesseract
                if self.config.get("tesseract_path"):
                    pytesseract.pytesseract.tesseract_cmd = str(self.config["tesseract_path"])
                text = pytesseract.image_to_string(image, timeout=2).strip()[:1600]
            except Exception as exc:
                ocr_error = str(exc)[:200]
            transition = next((word for word in TRANSITION_WORDS if word in text.lower()), "")
            result: dict[str, Any] = {
                "ok": True, "window_title": title[:120], "width": image.width, "height": image.height,
                "scene_hash": digest, "scene_changed": scene_changed, "ocr": text,
                "ocr_error": ocr_error,
                "transition": transition, "input_safe": not bool(transition), "epoch": time.time(),
            }
            if detailed:
                for _ in range(6):
                    buf = io.BytesIO()
                    image.save(buf, "JPEG", quality=65, optimize=True)
                    encoded = base64.b64encode(buf.getvalue()).decode("ascii")
                    if len(encoded) <= image_limit:
                        result["screenshot_jpeg_base64"] = encoded
                        break
                    image = image.resize((max(1, image.width * 3 // 4), max(1, image.height * 3 // 4)))
                if "screenshot_jpeg_base64" not in result:
                    result["screenshot_omitted"] = "compressed screenshot exceeded request limit"
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
        gamepad = VirtualGamepad(profile.input_backend) if profile.allow_controller else None
        self.input = InputSafetyController(profile, gamepad=gamepad)
        self.emergency_hotkey = EmergencyHotkey(self.input)
        self.vision = WindowVision(profile, config=config)
        self.media = NodeMediaClient(config)
        self.vrchat = None
        self._media_thread = None
        self._speech_queue = queue.Queue(maxsize=3)
        if config.get("vrchat_osc_enabled") and profile.platform == "vrchat":
            from .vrchat_osc import VrchatOsc
            self.vrchat = VrchatOsc(config.get("vrchat_send_port", 9000), config.get("vrchat_receive_port", 9001),
                                   gate=lambda: not self.input.disabled.is_set() and self.profile.allow_input)
        learning_template = str(config.get("game_learning_file") or "data/game-learning/{game_id}.json")
        learning_path = Path(learning_template.format(game_id=profile.game_id))
        self.learning = SkillLearningStore(learning_path, profile.game_id)
        self.realtime = RealtimeActionLoop(
            profile, self.input, self._safe_to_act,
            self._record_skill_result,
        )
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
        self.vrchat_friends = None
        self.vrchat_friends_log: deque[str] = deque(maxlen=20)
        if config.get("vrchat_friends_enabled") and config.get("vrchat_username") and config.get("vrchat_password"):
            from .vrchat_friends import VRChatFriendsService
            self.vrchat_friends = VRChatFriendsService(
                config, self._on_vrchat_friends_event, osc=self.vrchat,
            )
        from .world_mapper import WorldMapper
        self.world_mapper = WorldMapper(self)
        self.web_status = None
        if config.get("web_status_enabled"):
            from .web_status_server import WebStatusServer
            self.web_status = WebStatusServer(
                self, port=int(config.get("web_status_port", 8799)),
                frame_interval=float(config.get("web_status_frame_interval_seconds", 2.0)),
            )

    def capabilities(self) -> dict[str, dict[str, str]]:
        caps = {
            "game.status": {"kind": "read"}, "game.observe": {"kind": "read"},
            "game.capture": {"kind": "write"}, "game.input.stop": {"kind": "write"},
        }
        if self.profile.allow_input:
            caps["game.skill"] = {"kind": "write"}
            if self.profile.realtime_enabled and any(
                bool((self.profile.skill_metadata.get(name) or {}).get("realtime", False))
                for name in self.profile.skills
            ):
                caps["game.plan"] = {"kind": "write"}
        if self.config.get("windows_tts_enabled", True):
            caps["audio.speak"] = {"kind": "write"}
        if self.vrchat is not None:
            caps["vrchat.status"] = {"kind": "read"}
            for capability in ("vrchat.input", "vrchat.avatar.set", "vrchat.chatbox"):
                caps[capability] = {"kind": "write"}
        if self.profile.platform in {"xbox_remote_play", "playstation_remote_play"}:
            caps["console.status"] = {"kind": "read"}
        if self.profile.allow_obs:
            for name in ("obs.status", "obs.stream.status", "obs.scene", "obs.stream.start", "obs.stream.stop", "obs.record", "obs.replay.save"):
                caps[name] = {"kind": "read" if name in {"obs.status", "obs.stream.status"} else "write"}
        if self.profile.allow_twitch:
            caps.update({"twitch.chat.read": {"kind": "read"}, "twitch.chat.send": {"kind": "write"}})
        return caps

    def _safe_to_act(self) -> bool:
        if self.input.disabled.is_set() or not self.input.approved_window():
            return False
        latest = self.vision.capture()
        return bool(latest.get("ok") and latest.get("input_safe", True))

    def _record_skill_result(self, skill: str, ok: bool, duration_ms: float, reason: str = "") -> dict[str, Any]:
        if not self.profile.learning_enabled:
            return {}
        return self.learning.record(skill, ok, duration_ms, reason)

    def _on_vrchat_friends_event(self, text: str) -> None:
        self.vrchat_friends_log.append(f"{time.strftime('%H:%M:%S')}  {text}")
        try:
            if self.config.get("windows_tts_enabled", True):
                self._speech_queue.put_nowait((time.monotonic(), text))
        except queue.Full:
            pass

    def pair(self, pairing_id: str, pairing_code: str) -> str:
        response = self.session.post(
            self.server + "/api/nodes/register",
            json={
                "pairing_id": pairing_id, "pairing_code": pairing_code, "node_id": self.node_id,
                "name": str(self.config.get("name", "Windows Gaming Node")), "node_type": "windows-gaming",
                "capabilities": self.capabilities(),
            }, timeout=10, verify=self.verify_tls,
        )
        if not response.ok:
            try:
                detail = str(response.json().get("error") or response.reason)
            except (ValueError, AttributeError):
                detail = str(response.reason)
            raise RuntimeError(f"Node registration HTTP {response.status_code}: {detail}")
        self.token = str(response.json().get("device_token") or "")
        if not self.token:
            raise RuntimeError("Node registration returned no device token")
        return self.token

    def _headers(self) -> dict[str, str]:
        return {"X-Neko-Device-Token": self.token}

    def _telemetry(self) -> dict[str, Any]:
        _handle, title = WindowsWindow.foreground()
        state: dict[str, Any] = {
            "game_id": self.profile.game_id, "active_window": title[:120],
            "input_disabled": self.input.disabled.is_set(), "observation": self.vision.capture(),
            "last_command_result": self._last_result,
            "skills": self.learning.ranked(sorted(self.profile.skills)),
            "skill_metadata": self.profile.skill_metadata,
            "skill_learning": self.learning.snapshot(list(self.profile.skills)),
            "realtime": self.realtime.status(), "platform": self.profile.platform,
            "multiplayer_policy": self.profile.multiplayer_policy,
            "game_guide": self.profile.guide_summary[:1_500],
            "media": self.media.snapshot(),
            "windows_tts_enabled": bool(self.config.get("windows_tts_enabled", True)),
            "vrchat_friends": {
                "enabled": bool(self.vrchat_friends is not None),
                "running": bool(self.vrchat_friends is not None and self.vrchat_friends.is_running()),
                "recent_events": list(self.vrchat_friends_log),
            },
        }
        if self.vrchat is not None:
            state["vrchat"] = self.vrchat.status()
            try:
                from . import vrchat_logs
                log_dir = self.config.get("vrchat_log_dir") or None
                state["vrchat"]["world"] = vrchat_logs.current_world(log_dir)
                state["vrchat"]["players"] = vrchat_logs.nearby_players(log_dir)
            except Exception as exc:
                state["vrchat"]["log_error"] = str(exc)[:200]
        if self.profile.platform in {"xbox_remote_play", "playstation_remote_play"}:
            state["console"] = {
                "platform": self.profile.platform.removesuffix("_remote_play"),
                "remote_play_active": self.input.approved_window(),
                "current_title": "",
                "title_detection": "unavailable from the generic Remote Play window",
                "control_path": "approved Windows Remote Play window + virtual controller",
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
            self.world_mapper.stop()
            if self.vrchat is not None:
                self.vrchat.stop_input()
            self.realtime.cancel(disable=True); return {"ok": True, "input_disabled": True}
        if self.world_mapper.running and capability in {"game.skill", "game.plan", "vrchat.input", "vrchat.avatar.set"}:
            raise PermissionError("Manual world mapper owns movement; stop mapping before remote game control")
        if capability == "audio.speak":
            if not self.config.get("windows_tts_enabled", True):
                raise PermissionError("Windows speech output is disabled")
            self._speech_queue.put_nowait((time.monotonic(), str(args.get("text", ""))))
            return {"ok": True, "speech_queued": True}
        if capability.startswith("vrchat."):
            if self.vrchat is None:
                raise PermissionError("VRChat OSC is disabled")
            if capability == "vrchat.status":
                return self.vrchat.status()
            if capability == "vrchat.input":
                return self.vrchat.pulse(str(args.get("name", "")), args.get("value", 1), args.get("seconds", 0.25))
            if capability == "vrchat.avatar.set":
                return self.vrchat.avatar_parameter(str(args.get("name", "")), args.get("value"))
            if capability == "vrchat.chatbox":
                return self.vrchat.chatbox(str(args.get("text", "")))
        if capability == "game.skill":
            if self.profile.platform == "vrchat":
                from .vrchat_osc import SKILLS
                if self.vrchat is None or str(args.get("name", "")) not in SKILLS:
                    raise PermissionError("VRChat OSC skill unavailable")
                name, value = SKILLS[str(args["name"])]
                return self.vrchat.pulse(name, value, 0.25)
            self.realtime.cancel()
            skill, started = str(args.get("name", "")), time.monotonic()
            try:
                result = self.input.run_skill(skill)
                self._record_skill_result(skill, True, (time.monotonic() - started) * 1000)
                return result
            except Exception as exc:
                self._record_skill_result(skill, False, (time.monotonic() - started) * 1000, str(exc))
                raise
        if capability == "game.plan":
            return self.realtime.set_intent(str(args.get("name", "")), float(args.get("seconds", 3.0)))
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
            json={"node_id": self.node_id, "state": self._telemetry(), "capabilities": self.capabilities(), "ack_command_id": self._last_command or None},
        )
        response.raise_for_status()
        # A requested screenshot is delivered in one heartbeat only. Compact
        # action metadata remains available, but the image does not linger.
        self._last_result.pop("screenshot_jpeg_base64", None)
        poll = self.session.post(
            self.server + "/api/nodes/poll", headers=self._headers(), verify=self.verify_tls, timeout=30,
            json={"node_id": self.node_id, "after": self._last_command, "wait_seconds": 2},
        )
        poll.raise_for_status()
        for command in poll.json().get("commands", []):
            try: self._last_result = self._execute(command)
            except Exception as exc: self._last_result = {"ok": False, "error": str(exc)[:300]}
            self._last_command = max(self._last_command, int(command.get("id", 0)))
        return response.json()

    def _vision_loop(self) -> None:
        """Keep the cheap local OCR/scene-hash observation fresh on its own
        clock instead of only refreshing once per heartbeat.

        heartbeat_once() only builds a fresh observation when it happens to
        run, and each cycle is paced by the server poll's blocking wait (up
        to ~2s), so a game profile's own `capture_fps` (which can be set much
        higher for fast-paced games or short-lived text like a VRChat chat
        bubble) was previously capped at roughly one refresh per heartbeat
        regardless of that setting. WindowVision.capture() already throttles
        its own real work to the profile's capture_fps internally and returns
        the cached result otherwise, so calling it often here is cheap; it
        just means _telemetry()/_safe_to_act() always read an observation
        that's as fresh as the profile's capture_fps allows, independent of
        network/poll timing.
        """
        while not self._stop.is_set():
            try:
                self.vision.capture()
            except Exception:
                pass
            if self._stop.wait(0.05):
                break

    def _media_loop(self):
        last_vision = 0.0
        last_chatterbox_nudge = 0.0
        while not self._stop.is_set():
            try:
                if self.config.get("game_vision_enabled") and time.monotonic() - last_vision >= max(5, float(self.config.get("vision_interval_seconds", 10))):
                    last_vision = time.monotonic()
                    self.media.vision(self.vision.capture(detailed=True, image_limit=500_000))
                if self.config.get("audio_listen_enabled") and not self.media.speech_pending.is_set():
                    self.media.listen()
                    # Recording ends once it hears silence_seconds of quiet
                    # (they stopped talking), up to a hard max_seconds cap. If
                    # someone talks non-stop long enough to hit that cap
                    # without ever pausing, they get cut off with no natural
                    # end-point. Nudge them once in a while (not every single
                    # capture) instead of silently truncating them forever.
                    if self.media.audio.last_capture_truncated and time.monotonic() - last_chatterbox_nudge > 60:
                        last_chatterbox_nudge = time.monotonic()
                        try:
                            self._speech_queue.put_nowait((
                                time.monotonic(),
                                "Whoa, I'm not a chatterbox! Try pausing for a moment every so often "
                                "so I know when you're done talking.",
                            ))
                        except queue.Full:
                            pass
            except Exception as exc:
                self.media.update(error=str(exc)[:300])
            if self._stop.wait(1):
                break

    def _speech_loop(self):
        while not self._stop.is_set():
            try:
                created, text = self._speech_queue.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                if time.monotonic() - created < 30 and self.config.get("windows_tts_enabled", True):
                    self.media.speak(text)
            except Exception as exc:
                self.media.update(error=str(exc)[:300])

    def stop(self):
        self._stop.set()
        self.media.close()
        self.realtime.cancel(disable=True)
        self.world_mapper.stop()
        if self.web_status is not None:
            self.web_status.stop()
        if self.vrchat is not None:
            self.vrchat.stop_input()

    def _handle_connection_failure(self, exc: Exception) -> None:
        self.realtime.cancel()
        response = getattr(exc, "response", None)
        status = getattr(response, "status_code", None)
        temporary = isinstance(exc, (requests.ConnectionError, requests.Timeout)) or (
            isinstance(exc, requests.HTTPError) and status is not None and (status == 429 or 500 <= status < 600)
        )
        temporary = temporary and not isinstance(exc, requests.exceptions.SSLError)
        reason = f"Backend HTTP {status}" if status is not None else f"Backend {type(exc).__name__}"
        # Manual mapping is local, not a remotely supervised input session.
        # Never re-arm here: explicit stops and authentication failures stay stopped.
        if temporary and self.world_mapper.running and self.vrchat is not None and self.vrchat.armed.is_set():
            message = reason + "; manual mapping continues locally while reconnecting."
        else:
            self.world_mapper.stop()
            if self.vrchat is not None:
                self.vrchat.stop_input(reason=reason)
            message = reason + "; OSC disarmed."
        if getattr(self, "_connection_error", "") != message:
            self.world_mapper._emit(message)
        self._connection_error = message

    def run(self) -> None:
        if not self.token:
            raise RuntimeError("pair the agent first and store device_token in its config")
        try:
            if self.vrchat is not None:
                self.vrchat.start()
            self.emergency_hotkey.start()
            self.realtime.start()
            threading.Thread(target=self._vision_loop, daemon=True, name="windows-node-vision").start()
            self._media_thread = threading.Thread(target=self._media_loop, daemon=True, name="windows-node-media")
            self._media_thread.start()
            threading.Thread(target=self._speech_loop, daemon=True, name="windows-node-speech").start()
            if self.twitch is not None: self.twitch.start()
            if self.vrchat_friends is not None: self.vrchat_friends.start()
            if self.web_status is not None: self.web_status.start()
            while not self._stop.is_set():
                try:
                    self.heartbeat_once()
                    self._connection_error = ""
                except Exception as exc:
                    self._handle_connection_failure(exc)
                    if self._stop.wait(3): break
        finally:
            self.stop()
            if self.vrchat is not None:
                self.vrchat.close()
            self.emergency_hotkey.stop()
            self.realtime.stop()
            if self.twitch is not None: self.twitch.stop()
            if self.vrchat_friends is not None: self.vrchat_friends.stop()
            self.input.stop_all(disable=True)


def install_startup(config_path: Path, profile_path: Path | None = None, game: str = "", skills_root: Path | None = None) -> Path:
    if platform.system() != "Windows":
        raise RuntimeError("startup installation is available only on Windows")
    startup = Path(os.environ["APPDATA"]) / "Microsoft/Windows/Start Menu/Programs/Startup"
    target = startup / "NekoSuneAI-Windows-Gaming-Agent.cmd"
    selection = f'--profile "{profile_path}"' if profile_path else f'--skills-root "{skills_root}" --game "{game}"'
    target.write_text(f'@echo off\r\n"{sys.executable}" -m nekosuneai.windows_gaming_agent --config "{config_path}" {selection}\r\n', "utf-8")
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description="NekoSuneAI paired Windows Gaming Agent")
    parser.add_argument("--config", required=True)
    parser.add_argument("--profile", help="legacy standalone profile JSON")
    parser.add_argument("--skills-root", default="game-skills", help="folder containing versioned game skill packages")
    parser.add_argument("--game", help="game package id, such as minecraft or skyrim")
    parser.add_argument("--pairing-id", default="")
    parser.add_argument("--pairing-code", default="")
    parser.add_argument("--install-startup", action="store_true")
    args = parser.parse_args()
    if bool(args.profile) == bool(args.game):
        parser.error("choose exactly one of --profile or --game")
    config_path = Path(args.config).resolve()
    profile_path = Path(args.profile).resolve() if args.profile else None
    skills_root = Path(args.skills_root).resolve()
    config = json.loads(config_path.read_text("utf-8"))
    if profile_path:
        profile = GameProfile.load(profile_path)
    else:
        profile = GameProfile.from_mapping(GameSkillLibrary(skills_root).load(args.game).profile_mapping())
    if args.install_startup:
        print(install_startup(config_path, profile_path, args.game or "", skills_root)); return
    needs_interactive_pairing = (
        not config.get("device_token") and not (args.pairing_id and args.pairing_code)
    )
    if needs_interactive_pairing and not config.get("server_url"):
        print("No device token found; let's pair this node.")
        server_url = input(
            "Server address (e.g. https://your-server.example.com or https://1.2.3.4:8788): "
        ).strip()
        if not server_url:
            print("A server address is required to pair.", file=sys.stderr)
            sys.exit(1)
        config["server_url"] = server_url
    agent = WindowsGamingAgent(config, profile)
    if args.pairing_id and args.pairing_code:
        config["device_token"] = agent.pair(args.pairing_id, args.pairing_code)
        config_path.write_text(json.dumps(config, indent=2), "utf-8")
        print("Paired successfully; the device token was saved locally.")
    elif needs_interactive_pairing:
        pairing_id = input("Pairing ID: ").strip()
        pairing_code = input("Pairing code: ").strip()
        if not pairing_id or not pairing_code:
            print("Pairing ID and pairing code are both required.", file=sys.stderr)
            sys.exit(1)
        try:
            config["device_token"] = agent.pair(pairing_id, pairing_code)
        except Exception as exc:
            print(f"Pairing failed: {exc}", file=sys.stderr)
            sys.exit(1)
        config_path.write_text(json.dumps(config, indent=2), "utf-8")
        print("Paired successfully; the server address and device token were saved locally.")
    agent.run()


if __name__ == "__main__":
    main()
