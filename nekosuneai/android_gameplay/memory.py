from __future__ import annotations
import json
import re
from pathlib import Path
from typing import Any


def safe_name(value: str) -> str:
    value = (value or "generic").strip().lower()
    value = re.sub(r"[^a-z0-9._-]+", "_", value)
    return value[:100] or "generic"


class GameMemory:
    def __init__(self, directory: str, game_id: str, enabled: bool = True):
        self.enabled = enabled
        self.path = Path(directory) / f"{safe_name(game_id)}.json"
        self.data: dict[str, Any] = {
            "notes": [],
            "successful_actions": [],
            "failures": []
        }
        if self.enabled and self.path.exists():
            try:
                loaded = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    self.data.update(loaded)
            except Exception:
                pass

    def summary(self) -> dict[str, Any]:
        if not self.enabled:
            return {}
        return {
            "notes": self.data.get("notes", [])[-12:],
            "successful_actions": self.data.get("successful_actions", [])[-20:],
            "failures": self.data.get("failures", [])[-10:],
        }

    def remember_success(self, action: dict[str, Any]):
        if not self.enabled:
            return
        self.data.setdefault("successful_actions", []).append(action)
        self.data["successful_actions"] = self.data["successful_actions"][-100:]
        self.save()

    def remember_failure(self, message: str):
        if not self.enabled:
            return
        self.data.setdefault("failures", []).append(message)
        self.data["failures"] = self.data["failures"][-50:]
        self.save()

    def save(self):
        if not self.enabled:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
