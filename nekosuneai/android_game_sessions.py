"""Owner-authenticated Android game session API using existing paired nodes.

No arbitrary ADB/shell commands or input to unpaired targets. Commands are
queued through the existing capability registry so per-node policy applies.
"""
from __future__ import annotations
import re
import secrets
import threading
import time

_PACKAGE = re.compile(r"^[A-Za-z0-9_]+(?:[.][A-Za-z0-9_]+)+$")
_ACTIONS = frozenset(("tap", "swipe", "back"))
_OPERATIONS = frozenset(("start", "observe", "action", "stop", "pause", "resume", "emergency-stop", "autoplay", "autoplay-status"))


class AndroidGameSessions:
    def __init__(self, registry):
        self.registry = registry
        self.lock = threading.RLock()
        self.sessions = {}

    def devices(self):
        return [node for node in self.registry.list_nodes()
                if node.get("node_type") == "android-gaming"]

    def status(self, node_id):
        with self.lock:
            self._get_node(node_id)
            session = self.sessions.get(node_id)
            if session and session["expires_epoch"] <= time.time():
                self.sessions.pop(node_id, None)
                session = None
            if not session:
                return None
            node = self._get_node(node_id)
            state = node.get("state") or {}
            result = dict(session)
            result["device_session_id"] = state.get("session_id") or None
            result["device_input_disabled"] = state.get("input_disabled", True)
            result["device_autoplay"] = state.get("autoplay") or {"status": "unknown"}
            result["device_command_result"] = state.get("last_command_result") or {}
            result["device_confirmed"] = state.get("session_id") == session["session_id"]
            result["phase"] = "active" if result["device_confirmed"] else "awaiting-device"
            receipt = result["device_command_result"]
            if not result["device_confirmed"] and receipt.get("command_id") == session.get("start_command_id") and receipt.get("ok") is False:
                result["phase"] = "start-rejected"
            return result

    def _get_node(self, node_id):
        node = next((item for item in self.devices()
                     if item.get("node_id") == node_id), None)
        if not node or not node.get("online"):
            raise ValueError("The selected paired Android game node is offline")
        return node

    def command(self, operation, payload):
        if operation not in _OPERATIONS:
            raise ValueError("Unsupported game operation")
        node_id = str(payload.get("node_id") or "")
        with self.lock:
            self._get_node(node_id)
            now = time.time()
            session = self.sessions.get(node_id)
            if operation == "emergency-stop":
                queued = self.registry.enqueue(
                    node_id, "game.input.stop", {},
                    confirmed=True, requested_by="android-game-emergency-stop")
                self.sessions.pop(node_id, None)
                return {"ok": True, "operation": operation, "command": queued,
                        "session": None}
            if operation == "start":
                if session and session["expires_epoch"] > now:
                    raise ValueError("This Android node already has a session")
                game_id = str(payload.get("game_id") or "")
                if not _PACKAGE.fullmatch(game_id):
                    raise ValueError("Invalid Android package")
                duration = int(payload.get("duration_seconds", 300))
                max_actions = int(payload.get("max_actions", 100))
                if not 1 <= duration <= 3600 or not 1 <= max_actions <= 500:
                    raise ValueError("Invalid session limits")
                session_id = secrets.token_urlsafe(24)
                args = {"session_id": session_id, "game_id": game_id,
                        "duration_seconds": duration, "max_actions": max_actions,
                        "expires_epoch": now + 10}
                capability = "game.session.start"
                next_session = {"session_id": session_id, "game_id": game_id,
                                "expires_epoch": now + duration,
                                "max_actions": max_actions, "actions_queued": 0}
            else:
                if not session or session["expires_epoch"] <= now:
                    self.sessions.pop(node_id, None)
                    raise ValueError("No active game session in Main")
                if payload.get("session_id") != session["session_id"]:
                    raise PermissionError("Session mismatch")
                args = {"session_id": session["session_id"]}
                next_session = None
                capability = {"observe": "game.observe", "action": "game.action",
                              "autoplay": "game.autoplay.start", "autoplay-status": "game.autoplay.status",
                              "stop": "game.session.stop", "pause": "game.session.pause",
                              "resume": "game.session.resume"}[operation]
                if operation == "autoplay":
                    goal = payload.get("goal")
                    if not isinstance(goal, str) or not 1 <= len(goal.strip()) <= 500:
                        raise ValueError("Autoplay requires a 1–500 character owner goal")
                    args["goal"] = goal.strip()
                    args["expires_epoch"] = now + 10
                if operation == "observe":
                    args["analyze"] = payload.get("analyze") is True
                if operation == "action":
                    if session["actions_queued"] >= session["max_actions"]:
                        raise PermissionError("Action budget exhausted")
                    action = payload.get("action")
                    if not isinstance(action, dict) or action.get("type") not in _ACTIONS:
                        raise ValueError("Only bounded tap/swipe/back actions are supported")
                    kind = action["type"]
                    if kind in ("tap", "swipe"):
                        fields = ("x", "y") if kind == "tap" else ("x1", "y1", "x2", "y2")
                        if any(type(action.get(field)) is not int or not 0 <= action[field] <= 16384
                               for field in fields):
                            raise ValueError("Invalid coordinates")
                    if kind == "swipe":
                        duration = action.get("duration_ms", 350)
                        if type(duration) is not int or not 50 <= duration <= 1500:
                            raise ValueError("Invalid swipe duration")
                    args.update({"game_id": session["game_id"],
                                 "action": {k: v for k, v in action.items()
                                            if k in {"type","x","y","x1","y1","x2","y2","duration_ms"}},
                                 "expires_epoch": now + 10})
            # Existing registry owner confirmation policy is always checked.
            queued = self.registry.enqueue(node_id, capability, args,
                                           confirmed=payload.get("confirmed") is True,
                                           requested_by="android-game-dashboard")
            if operation == "start":
                next_session["start_command_id"] = queued["id"]
                self.sessions[node_id] = next_session
            elif operation == "stop":
                self.sessions.pop(node_id, None)
            elif operation == "action":
                session["actions_queued"] += 1
            return {"ok": True, "operation": operation, "command": queued,
                    "session": self.sessions.get(node_id)}
