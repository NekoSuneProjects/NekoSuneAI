"""GameDriver for an explicitly paired Windows Gaming Node.

The core never receives arbitrary keyboard input.  It observes compact node
telemetry and may queue only a named skill declared by the local game profile.
"""
from __future__ import annotations

from typing import Any

from ..peripheral_nodes import PeripheralNodeRegistry
from .base import GameCommand, GameObservation


class WindowsRemoteGameDriver:
    """Drive one online Windows gaming node through its scoped capabilities."""

    name = "paired Windows game"

    def __init__(self, registry: PeripheralNodeRegistry) -> None:
        self.registry = registry
        self._node_id = ""
        self._running = False
        self._last_observation = GameObservation(text="No observation yet.")

    def _node(self) -> dict[str, Any]:
        nodes = [
            node for node in self.registry.list_nodes()
            if node.get("node_type") == "windows-gaming" and node.get("online")
        ]
        if not nodes:
            raise RuntimeError("No online paired Windows Gaming Node was found.")
        if len(nodes) > 1:
            raise RuntimeError("More than one Windows Gaming Node is online; disconnect the unused node.")
        return nodes[0]

    def start(self) -> None:
        node = self._node()
        node_id = str(node["node_id"])
        state = dict(node.get("state") or {})
        if not state.get("game_running"):
            raise RuntimeError("The approved game is not running on the Windows node.")
        if state.get("input_disabled"):
            raise RuntimeError("Windows game input is locally disabled; re-enable it on the gaming PC.")
        if self.registry.action_policy(node_id, "game.skill") != "allow":
            raise PermissionError(
                "Autonomous play is disabled. In Peripheral Nodes, explicitly set game.skill to allow."
            )
        self._node_id = node_id
        self.name = f"Windows: {state.get('game_id') or 'approved game'}"
        self._running = True

    def stop(self) -> None:
        node_id, self._running = self._node_id, False
        if not node_id:
            return
        try:
            self.registry.enqueue(
                node_id, "game.input.stop", {}, confirmed=True, requested_by="game-agent-stop",
            )
        except (PermissionError, ValueError):
            # The Windows node independently releases held keys on disconnect.
            pass

    def is_running(self) -> bool:
        if not self._running:
            return False
        try:
            node = self._node()
            return str(node.get("node_id")) == self._node_id and bool((node.get("state") or {}).get("game_running"))
        except RuntimeError:
            return False

    def observe(self) -> GameObservation:
        node = self._node()
        if str(node.get("node_id")) != self._node_id:
            raise RuntimeError("The paired Windows Gaming Node changed during the session.")
        state = dict(node.get("state") or {})
        observation = dict(state.get("observation") or {})
        if not state.get("game_running"):
            raise RuntimeError("The approved game stopped running.")
        if state.get("input_disabled"):
            raise PermissionError("Windows game input was stopped locally.")

        parts = [
            f"Game: {state.get('game_id') or 'unknown'}",
            f"Window: {state.get('active_window') or 'unknown'}",
        ]
        if observation.get("ocr"):
            parts.append(f"Visible text: {str(observation['ocr'])[:500]}")
        if observation.get("transition"):
            parts.append(f"Scene transition: {str(observation['transition'])[:80]}")
        parts.append(f"Visual scene hash: {observation.get('scene_hash') or 'unavailable'}")
        raw = {
            "game_id": state.get("game_id"),
            "active_window": state.get("active_window"),
            "scene_hash": observation.get("scene_hash"),
            "scene_changed": bool(observation.get("scene_changed")),
            "transition": observation.get("transition"),
            "input_safe": bool(observation.get("input_safe", True)),
            "last_command_result": state.get("last_command_result"),
            "realtime": state.get("realtime"),
            "skill_learning": state.get("skill_learning"),
        }
        self._last_observation = GameObservation(raw=raw, text="\n".join(parts))
        return self._last_observation

    def describe_state(self) -> str:
        return self._last_observation.text

    def mission(self) -> str:
        try:
            guide = str((self._node().get("state") or {}).get("game_guide") or "").strip()
            return "Game package guide:\n" + guide if guide else ""
        except RuntimeError:
            return ""

    def verbs_help(self) -> str:
        try:
            metadata = dict((self._node().get("state") or {}).get("skill_metadata") or {})
            lines = [
                f"{name}: {str((metadata.get(name) or {}).get('description') or '')}"
                for name in self.available_verbs()
            ]
            return "Approved skill meanings:\n" + "\n".join(lines) if lines else ""
        except RuntimeError:
            return ""

    def available_verbs(self) -> list[str]:
        try:
            skills = (self._node().get("state") or {}).get("skills") or []
            return [str(skill) for skill in skills if str(skill).strip()]
        except RuntimeError:
            return []

    def act(self, command: GameCommand) -> dict[str, Any]:
        if not self._running:
            raise RuntimeError("The Windows game driver is not running.")
        if command.verb == "wait":
            return {"ok": True, "skill": "wait", "queued": False}
        verbs = self.available_verbs()
        if command.verb not in verbs:
            raise ValueError(f"Unknown or unapproved game skill: {command.verb}")
        raw = self._last_observation.raw
        if raw.get("transition") or raw.get("input_safe") is False:
            raise PermissionError("Input is paused during an unsafe or transitional visual state.")
        node = self._node()
        metadata = dict(((node.get("state") or {}).get("skill_metadata") or {}).get(command.verb) or {})
        capability = (
            "game.plan" if metadata.get("realtime")
            and "game.plan" in (node.get("capabilities") or {})
            and self.registry.action_policy(self._node_id, "game.plan") == "allow"
            else "game.skill"
        )
        arguments = {"name": command.verb}
        if capability == "game.plan":
            arguments["seconds"] = max(0.25, min(float(command.args.get("seconds", 8.0)), 8.0))
        item = self.registry.enqueue(
            self._node_id, capability, arguments,
            confirmed=False, requested_by="windows-game-agent",
        )
        return {
            "ok": True, "skill": command.verb, "queued": True,
            "realtime": capability == "game.plan", "command_id": item["id"],
        }
