"""VRChat driver via the official OSC API.

Uses VRChat's built-in OSC API (enable OSC in VRChat's Action Menu) to walk,
strafe, run, look, jump, type in the chatbox, and set avatar parameters/emotes —
the *supported*, TOS-friendly way to drive an avatar (no input injection, no
process tampering, EAC-safe).

Beyond sending, this driver also:
  * **Receives** VRChat's standard avatar OSC params (Velocity/Grounded) on a
    listen port, so NekoSuneAI feels its own motion — used to notice it's stuck
    against a wall or falling off a ledge (VRChat exposes no world geometry).
  * Reads VRChat's **logs** for the current world and who's in the instance
    ("who's here?") with zero web-API calls and no GPU (see ``vrchat_logs``).
  * Optionally **sees** the screen when a VISION_MODEL is set (screen caption).
"""
from __future__ import annotations

import math
import threading
import time
from typing import Any

from ..config import Config
from . import screen, vrchat_logs
from .base import GameCommand, GameObservation

_VERBS = ["walk", "back", "strafe", "turn", "run", "jump", "say", "emote", "look", "wait"]

# VRChat's standard locomotion-detection avatar parameters (what the receiver
# listens for). These are emitted by most avatars; absent ones just stay None.
_POSE_PARAMS = {
    "/avatar/parameters/VelocityX": "vx",
    "/avatar/parameters/VelocityY": "vy",
    "/avatar/parameters/VelocityZ": "vz",
    "/avatar/parameters/Grounded": "grounded",
    "/avatar/parameters/Upright": "upright",
}


class VRChatDriver:
    name = "VRChat"

    def __init__(self, config: Config) -> None:
        self.config = config
        self._client: Any = None
        self._server: Any = None
        self._server_thread: threading.Thread | None = None
        self._pose_lock = threading.Lock()
        self._pose: dict[str, float | bool | None] = {
            "vx": None, "vy": None, "vz": None, "grounded": None, "upright": None
        }
        self._running_hold = False          # whether the Run button is held
        self._last_move_at = 0.0            # when we last commanded forward/back
        self._last_move_kind = ""           # "walk" | "back" | ""

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def start(self) -> None:
        try:
            from pythonosc.udp_client import SimpleUDPClient  # type: ignore
        except Exception as exc:  # pragma: no cover - optional dep
            raise RuntimeError("python-osc is not installed. Run: pip install python-osc") from exc
        self._client = SimpleUDPClient(self.config.vrchat_osc_host, self.config.vrchat_osc_port)
        self._start_receiver()

    def _start_receiver(self) -> None:
        """Listen for VRChat's avatar OSC params so we can feel our own motion."""
        try:
            from pythonosc.dispatcher import Dispatcher  # type: ignore
            from pythonosc.osc_server import ThreadingOSCUDPServer  # type: ignore
        except Exception:
            return  # receiver is best-effort; sending still works without it
        disp = Dispatcher()
        for address, key in _POSE_PARAMS.items():
            disp.map(address, self._on_pose, key)
        try:
            port = int(getattr(self.config, "vrchat_osc_read_port", 9001))
            self._server = ThreadingOSCUDPServer(("127.0.0.1", port), disp)
        except Exception:
            self._server = None
            return
        self._server_thread = threading.Thread(
            target=self._server.serve_forever, name="NekoSuneAIVRChatOSC", daemon=True
        )
        self._server_thread.start()

    def _on_pose(self, address: str, key: str, *args: Any) -> None:
        if not args:
            return
        val = args[0]
        with self._pose_lock:
            if key == "grounded":
                self._pose["grounded"] = bool(val)
            else:
                try:
                    self._pose[key] = float(val)
                except (TypeError, ValueError):
                    pass

    def stop(self) -> None:
        if self._server is not None:
            try:
                self._server.shutdown()
            except Exception:
                pass
        self._server = None
        self._client = None

    def is_running(self) -> bool:
        return self._client is not None

    # ── pose / awareness ──────────────────────────────────────────────────────

    def _pose_snapshot(self) -> dict[str, Any]:
        with self._pose_lock:
            p = dict(self._pose)
        vx, vz = p.get("vx"), p.get("vz")
        speed = None
        if vx is not None and vz is not None:
            speed = math.hypot(float(vx), float(vz))
        return {
            "speed": speed,
            "vy": p.get("vy"),
            "grounded": p.get("grounded"),
            "has_velocity": speed is not None,
        }

    def _motion_note(self, pose: dict[str, Any]) -> str:
        """Turn raw pose into a hint the agent can act on (wall / ledge / moving)."""
        notes = []
        speed, vy, grounded = pose["speed"], pose["vy"], pose["grounded"]
        recently_moved = (time.time() - self._last_move_at) < 4.0 and self._last_move_kind
        if pose["has_velocity"]:
            if recently_moved and grounded is not False and speed is not None and speed < 0.15:
                notes.append(
                    "I pushed forward but barely moved — there's likely a WALL ahead. "
                    "Turn left or right before walking again."
                )
            elif speed is not None and speed > 0.3:
                notes.append(f"I'm moving (~{speed:.1f} m/s).")
            if vy is not None and vy < -1.0:
                notes.append("I'm airborne and falling — careful of a LEDGE or drop; back up.")
        return " ".join(notes)

    def observe(self) -> GameObservation:
        parts: list[str] = []
        raw: dict[str, Any] = {}

        # 1) Who's here + which world (free, from VRChat logs).
        log_dir = getattr(self.config, "vrchat_log_dir", None)
        try:
            world = vrchat_logs.current_world(log_dir)
        except Exception:
            world = None
        try:
            players = vrchat_logs.nearby_players(log_dir)
        except Exception:
            players = []
        if world and (world.get("name") or world.get("id")):
            raw["world"] = world
            parts.append(f"World: {world.get('name') or world.get('id')}.")
        if players:
            raw["players"] = players
            shown = ", ".join(players[:8]) + (" …" if len(players) > 8 else "")
            parts.append(f"People here ({len(players)}): {shown}.")
        else:
            parts.append("No other players detected nearby.")

        # 2) Self-motion feedback (wall / ledge / moving) from received OSC.
        pose = self._pose_snapshot()
        raw["pose"] = pose
        motion = self._motion_note(pose)
        if motion:
            parts.append(motion)

        # 3) Optional vision (screen caption) when a model is configured.
        if self.config.vision_model:
            png = screen.capture_png()
            if png is not None:
                text = screen.caption(
                    self.config, png,
                    "You are the eyes of an AI in VRChat. Describe the room/world, nearby "
                    "players or avatars, menus, and anything interesting to walk toward. Be concise.",
                )
                if text:
                    raw["scene"] = text
                    parts.append(f"I see: {text}")
        elif not parts:
            parts.append(
                "In VRChat (OSC control). No vision model set, so I can't see the world; "
                "I can still walk, turn, run, jump, emote, and chat."
            )
        return GameObservation(raw=raw, text=" ".join(parts))

    def describe_state(self) -> str:
        return self.observe().text

    # ── sending ───────────────────────────────────────────────────────────────

    def _send(self, address: str, value: Any) -> None:
        if self._client is not None:
            self._client.send_message(address, value)

    def _timed_axis(self, address: str, value: float, seconds: float) -> None:
        seconds = max(0.0, min(6.0, float(seconds)))
        self._send(address, float(value))
        time.sleep(seconds)
        self._send(address, 0.0)

    def act(self, command: GameCommand) -> dict[str, Any]:
        if self._client is None:
            return {"ok": False, "message": "not connected"}
        verb = command.verb
        args = command.args or {}
        try:
            if verb == "walk":
                self._last_move_at, self._last_move_kind = time.time(), "walk"
                self._timed_axis("/input/Vertical", 1.0, args.get("seconds", 1.5))
                return {"ok": True, "message": "walked forward"}
            if verb == "back":
                self._last_move_at, self._last_move_kind = time.time(), "back"
                self._timed_axis("/input/Vertical", -1.0, args.get("seconds", 1.0))
                return {"ok": True, "message": "walked back"}
            if verb == "strafe":
                direction = 1.0 if str(args.get("direction", "right")).lower() == "right" else -1.0
                self._timed_axis("/input/Horizontal", direction, args.get("seconds", 1.0))
                return {"ok": True, "message": f"strafed {args.get('direction', 'right')}"}
            if verb == "turn":
                direction = 1.0 if str(args.get("direction", "right")).lower() == "right" else -1.0
                self._timed_axis("/input/LookHorizontal", direction, args.get("seconds", 0.6))
                return {"ok": True, "message": f"turned {args.get('direction', 'right')}"}
            if verb == "look":
                # Look up/down briefly (e.g. to read a sign or see a face).
                direction = 1.0 if str(args.get("direction", "up")).lower() == "up" else -1.0
                self._timed_axis("/input/LookVertical", direction, args.get("seconds", 0.4))
                return {"ok": True, "message": f"looked {args.get('direction', 'up')}"}
            if verb == "run":
                on = bool(args.get("value", not self._running_hold))
                self._running_hold = on
                self._send("/input/Run", 1 if on else 0)
                return {"ok": True, "message": f"run {'on' if on else 'off'}"}
            if verb == "jump":
                self._send("/input/Jump", 1)
                time.sleep(0.15)
                self._send("/input/Jump", 0)
                return {"ok": True, "message": "jumped"}
            if verb == "say":
                text = str(args.get("text", ""))[:140]
                # Brief typing indicator, then post immediately (no notify sfx).
                self._send("/chatbox/typing", True)
                time.sleep(0.2)
                self._send("/chatbox/typing", False)
                self._send("/chatbox/input", [text, True, False])
                return {"ok": True, "message": "sent to chatbox"}
            if verb == "emote":
                name = str(args.get("param", "")).strip()
                if not name:
                    return {"ok": False, "message": "emote needs a param name"}
                self._send(f"/avatar/parameters/{name}", args.get("value", 1))
                return {"ok": True, "message": f"set {name}"}
            if verb == "wait":
                return {"ok": True, "message": "waited"}
            return {"ok": False, "message": f"unknown verb {verb}"}
        except Exception as exc:
            return {"ok": False, "message": str(exc)}

    def available_verbs(self) -> list[str]:
        return list(_VERBS)

    def default_goal(self) -> str:
        return "Hang out in VRChat: wander around, look at people/places, and chat with players."

    def mission(self) -> str:
        return (
            "You are an avatar in VRChat (controlled via OSC). Do NOT use Minecraft "
            "commands (no !mine/!searchForBlock/etc.) — they do nothing here. Move "
            "around, look, and chat naturally with people; greet people by name when "
            "you can see who's here. If you bump a wall or near a ledge, turn before "
            "walking again. One action per turn."
        )

    def verbs_help(self) -> str:
        return (
            "Args go in args.\n"
            "walk{seconds?} = forward | back{seconds?} = step back | "
            "strafe{direction:'left'|'right',seconds?} = sidestep | "
            "turn{direction:'left'|'right',seconds?} = turn | "
            "look{direction:'up'|'down',seconds?} = tilt view | "
            "run{value?bool} = toggle running | jump = jump | "
            "say{text} = talk in the chatbox | emote{param,value?} = avatar "
            "expression | wait = idle this turn."
        )
