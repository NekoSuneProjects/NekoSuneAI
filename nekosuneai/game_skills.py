"""Versioned, data-only game skill packages and bounded reliability learning."""
from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


GAME_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,63}$")
SKILL_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{1,63}$")
POLICIES = {"single_player", "private_server", "permitted_multiplayer", "prohibited"}
STEP_INPUTS = {"key", "mouse_button", "mouse_move", "button", "axis", "wait"}


def validate_skill_step(step: dict[str, Any]) -> None:
    inputs = STEP_INPUTS.intersection(step)
    if len(inputs) != 1:
        raise ValueError("each skill step must contain exactly one approved input type")
    if set(step) - STEP_INPUTS - {"seconds", "value"}:
        raise ValueError("skill step contains unsupported fields")
    seconds = float(step.get("seconds", 0.1))
    if seconds < 0 or seconds > 2:
        raise ValueError("skill step duration must be between zero and two seconds")
    if "mouse_move" in step:
        move = step["mouse_move"]
        if not isinstance(move, dict) or set(move) - {"x", "y"}:
            raise ValueError("mouse_move accepts only x/y")
        if any(abs(int(move.get(axis, 0))) > 250 for axis in ("x", "y")):
            raise ValueError("mouse movement exceeds the bounded range")


@dataclass(frozen=True)
class GameSkillPackage:
    game_id: str
    display_name: str
    root: Path
    guide: str
    profile: dict[str, Any]
    skills: dict[str, list[dict[str, Any]]]
    skill_metadata: dict[str, dict[str, Any]]

    def profile_mapping(self) -> dict[str, Any]:
        return {
            **self.profile,
            "game_id": self.game_id,
            "display_name": self.display_name,
            "skills": self.skills,
            "skill_metadata": self.skill_metadata,
            "guide_summary": self.guide[:4_000],
        }


class GameSkillLibrary:
    """Discover independently selectable ``game.json`` packages."""

    def __init__(self, root: str | Path = "game-skills") -> None:
        self.root = Path(root)

    def discover(self) -> list[dict[str, Any]]:
        packages = []
        if not self.root.exists():
            return packages
        for path in sorted(self.root.glob("*/game.json")):
            try:
                package = self.load(path.parent.name)
                packages.append({
                    "game_id": package.game_id,
                    "display_name": package.display_name,
                    "platform": package.profile.get("platform", "windows"),
                    "multiplayer_policy": package.profile.get("multiplayer_policy", "single_player"),
                    "skill_count": len(package.skills),
                })
            except (OSError, ValueError, json.JSONDecodeError):
                continue
        return packages

    def load(self, game_id: str) -> GameSkillPackage:
        game_id = str(game_id).strip().lower()
        if not GAME_ID_RE.fullmatch(game_id):
            raise ValueError("invalid game package id")
        package_root = (self.root / game_id).resolve()
        library_root = self.root.resolve()
        if package_root.parent != library_root:
            raise ValueError("game package must be directly inside the skill library")
        raw = json.loads((package_root / "game.json").read_text("utf-8"))
        if int(raw.get("schema_version", 0)) != 1:
            raise ValueError("unsupported game skill schema version")
        if str(raw.get("game_id", "")).strip().lower() != game_id:
            raise ValueError("game package id does not match its folder")
        display_name = str(raw.get("display_name") or game_id).strip()[:100]
        profile = dict(raw.get("profile") or {})
        policy = str(profile.get("multiplayer_policy", "single_player"))
        if policy not in POLICIES:
            raise ValueError("invalid multiplayer policy")
        definitions = raw.get("skills") or {}
        if not isinstance(definitions, dict) or not definitions:
            raise ValueError("game package must define at least one skill")
        skills: dict[str, list[dict[str, Any]]] = {}
        metadata: dict[str, dict[str, Any]] = {}
        for name, definition in definitions.items():
            if not SKILL_RE.fullmatch(str(name)) or not isinstance(definition, dict):
                raise ValueError("invalid game skill definition")
            steps = definition.get("steps")
            if not isinstance(steps, list) or not steps or len(steps) > 20:
                raise ValueError(f"{name} must contain 1-20 steps")
            skills[str(name)] = [dict(step) for step in steps if isinstance(step, dict)]
            if len(skills[str(name)]) != len(steps):
                raise ValueError(f"{name} contains an invalid step")
            for step in skills[str(name)]:
                validate_skill_step(step)
            metadata[str(name)] = {
                "description": str(definition.get("description") or "")[:300],
                "realtime": bool(definition.get("realtime", False)),
                "tags": [str(tag)[:40] for tag in (definition.get("tags") or [])[:12]],
            }
        if "wait" not in skills:
            skills["wait"] = [{"wait": True, "seconds": 0.1}]
            metadata["wait"] = {
                "description": "Release input and wait for a safer or clearer observation.",
                "realtime": False, "tags": ["safety"],
            }
        guide_path = package_root / "GUIDE.md"
        guide = guide_path.read_text("utf-8")[:20_000] if guide_path.exists() else ""
        return GameSkillPackage(game_id, display_name, package_root, guide, profile, skills, metadata)


class SkillLearningStore:
    """Aggregate approved skill outcomes without retaining frames or key events."""

    def __init__(self, path: str | Path, game_id: str) -> None:
        self.path = Path(path)
        self.game_id = game_id
        self._lock = threading.RLock()
        self._skills: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        try:
            raw = json.loads(self.path.read_text("utf-8"))
            if raw.get("game_id") == self.game_id and isinstance(raw.get("skills"), dict):
                restored: dict[str, dict[str, Any]] = {}
                for name, value in list(raw["skills"].items())[:256]:
                    if not SKILL_RE.fullmatch(str(name)) or not isinstance(value, dict):
                        continue
                    attempts = max(0, min(int(value.get("attempts", 0)), 1_000_000))
                    successes = max(0, min(int(value.get("successes", 0)), attempts))
                    restored[str(name)] = {
                        "attempts": attempts, "successes": successes, "failures": attempts - successes,
                        "reliability": round(successes / attempts, 4) if attempts else 0.5,
                        "average_duration_ms": max(0.0, min(float(value.get("average_duration_ms", 0)), 600_000.0)),
                        "last_result": "success" if value.get("last_result") == "success" else "failure",
                        "last_reason": str(value.get("last_reason") or "")[:240],
                        "last_epoch": max(0.0, float(value.get("last_epoch", 0))),
                    }
                self._skills = restored
        except Exception:
            self._skills = {}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(self.path.suffix + ".tmp")
        temp.write_text(json.dumps({
            "schema_version": 1, "game_id": self.game_id,
            "updated_epoch": time.time(), "skills": self._skills,
        }, indent=2, sort_keys=True), "utf-8")
        temp.replace(self.path)

    def record(self, skill: str, ok: bool, duration_ms: float, reason: str = "") -> dict[str, Any]:
        if not SKILL_RE.fullmatch(str(skill)):
            raise ValueError("invalid skill name")
        with self._lock:
            row = dict(self._skills.get(skill) or {})
            attempts = int(row.get("attempts", 0)) + 1
            successes = int(row.get("successes", 0)) + int(bool(ok))
            previous_average = float(row.get("average_duration_ms", 0.0))
            row.update({
                "attempts": attempts,
                "successes": successes,
                "failures": attempts - successes,
                "reliability": round(successes / attempts, 4),
                "average_duration_ms": round(previous_average + (float(duration_ms) - previous_average) / attempts, 2),
                "last_result": "success" if ok else "failure",
                "last_reason": "" if ok else str(reason)[:240],
                "last_epoch": time.time(),
            })
            self._skills[skill] = row
            self._save()
            return dict(row)

    def snapshot(self, allowed_skills: list[str] | None = None) -> dict[str, dict[str, Any]]:
        allowed = set(allowed_skills or self._skills)
        with self._lock:
            return {name: dict(row) for name, row in self._skills.items() if name in allowed}

    def ranked(self, skills: list[str]) -> list[str]:
        with self._lock:
            return sorted(
                skills,
                key=lambda name: (
                    -float((self._skills.get(name) or {}).get("reliability", 0.5)),
                    -int((self._skills.get(name) or {}).get("attempts", 0)),
                    name,
                ),
            )
