"""High-level, confirmation-gated supervision for a paired Windows stream node."""
from __future__ import annotations

import re
from typing import Any, Callable

from .home_events import HomeEventTimeline


NodeProvider = Callable[[], list[dict[str, Any]]]
CommandSender = Callable[..., dict[str, Any]]


class StreamSessionManager:
    def __init__(self, nodes: NodeProvider, send: CommandSender, timeline: HomeEventTimeline) -> None:
        self.nodes, self.send, self.timeline = nodes, send, timeline

    def _node(self) -> dict[str, Any]:
        candidates = [row for row in self.nodes() if row.get("node_type") == "windows-gaming"]
        if not candidates:
            raise ValueError("no Windows Gaming Node is paired")
        online = [row for row in candidates if row.get("online")]
        if not online:
            raise ValueError("the Windows Gaming Node is offline")
        if len(online) > 1:
            raise ValueError("more than one Windows Gaming Node is online; use the dashboard")
        return online[0]

    def preflight(self, game: str = "") -> dict[str, Any]:
        try:
            node = self._node()
        except ValueError as exc:
            return {"ready": False, "checks": {"windows_node": False}, "blockers": [str(exc)]}
        state = dict(node.get("state") or {})
        obs = dict(state.get("obs") or {})
        vision = dict(state.get("observation") or {})
        checks = {
            "windows_node": True,
            "game_profile": bool(state.get("game_id")),
            "game_running": bool(state.get("game_running")),
            "approved_window_capture": bool(vision.get("ok")),
            "obs_connected": bool(obs.get("connected")),
            "stream_not_already_active": not bool(obs.get("streaming")),
            "input_emergency_stop_available": "game.input.stop" in (node.get("capabilities") or {}),
        }
        if game and str(state.get("game_id", "")).casefold() != game.casefold():
            checks["requested_game_profile"] = False
        blockers = [name.replace("_", " ") for name, passed in checks.items() if not passed]
        return {"ready": not blockers, "checks": checks, "blockers": blockers, "node": node["node_id"]}

    def action(self, action: str, *, confirmed: bool = False, value: str = "") -> dict[str, Any]:
        node = self._node()
        node_id = str(node["node_id"])
        mapping = {
            "start_stream": ("obs.stream.start", {}),
            "stop_stream": ("obs.stream.stop", {}),
            "stop_input": ("game.input.stop", {}),
            "brb": ("obs.scene", {"scene": value or "BRB"}),
            "gameplay": ("obs.scene", {"scene": value or "Gameplay"}),
            "ending": ("obs.scene", {"scene": value or "Ending"}),
        }
        if action not in mapping:
            raise ValueError("unsupported stream supervision action")
        if action in {"start_stream", "stop_stream"} and not confirmed:
            return {"status": "confirmation_required", "action": action}
        capability, arguments = mapping[action]
        command = self.send(
            node_id, capability, arguments, confirmed=confirmed,
            requested_by="stream-supervision",
        )
        self.timeline.record(
            "stream", f"stream.{action}", f"Queued {action.replace('_', ' ')} on {node.get('name', node_id)}.",
            source=node_id, details={"command_id": command.get("id")},
        )
        return {"status": "queued", "action": action, "command": command}

    def status(self) -> dict[str, Any]:
        node = self._node()
        state = dict(node.get("state") or {})
        return {
            "node_id": node["node_id"], "online": node.get("online"), "game_id": state.get("game_id"),
            "game_running": state.get("game_running"), "active_window": state.get("active_window"),
            "input_disabled": state.get("input_disabled"), "obs": state.get("obs", {}),
            "last_command_result": state.get("last_command_result", {}),
        }

    def handle(self, text: str) -> str | None:
        lower = " ".join(text.strip().lower().split())
        match = re.match(r"^(?:neko[, ]+)?(?:prepare|check) (?:a )?stream(?: for)? (.+)$", lower)
        if match:
            result = self.preflight(match.group(1).strip())
            return "Stream preflight passed." if result["ready"] else "Stream preflight blocked: " + ", ".join(result["blockers"]) + "."
        if re.fullmatch(r"(?:neko[, ]+)?(?:stream|streaming) status[?]?", lower):
            status = self.status(); obs = status.get("obs") or {}
            return f"Windows node online; game {status.get('game_id') or 'unknown'}; OBS {'connected' if obs.get('connected') else 'disconnected'}; stream {'live' if obs.get('streaming') else 'offline'}."
        match = re.fullmatch(r"(?:neko[, ]+)?(?:(confirm) )?(start|stop) (?:the )?stream[.!]?", lower)
        if match:
            result = self.action(f"{match.group(2)}_stream", confirmed=bool(match.group(1)))
            return "Queued the stream command." if result["status"] == "queued" else "Starting or stopping the live stream needs explicit confirmation."
        if re.fullmatch(r"(?:neko[, ]+)?(?:stop all game input|pause neko|take over)[.!]?", lower):
            self.action("stop_input", confirmed=True)
            return "Stopped and disabled all AI game input on the Windows node."
        return None
