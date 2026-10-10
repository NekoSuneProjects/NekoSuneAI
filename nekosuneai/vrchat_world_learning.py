"""VRChat Among Us observer: bounded, read-only world learning.

This module deliberately cannot send OSC, keyboard or mouse inputs.
Navigation, interaction and social entries are *suggestions*, not actions.
"""
from __future__ import annotations
import json
import os
import re
import tempfile
import time
from pathlib import Path

WORLD = "among-us"
STAGES = {
    "lobby": ("waiting for players", "start game", "game starts"),
    "tasks": ("tasks", "complete task", "fix wiring", "upload data", "swipe card"),
    "meeting": ("emergency meeting", "who is the impostor", "discussion"),
    "voting": ("vote", "skip vote", "voting ends", "remaining time"),
    "result": ("victory", "defeat", "crewmates win", "impostors win"),
}
SOCIAL_MARKERS = ("meeting", "vote", "discussion", "emergency")
INTERACTIONS = ("use", "interact", "report", "emergency", "task")
MAX_OBSERVATIONS = 250
MAX_TEXT = 1200

def detect_stage(text: str) -> tuple[str, list[str]]:
    clean = re.sub(r"\s+", " ", text.lower())
    scores = {stage: sum(1 for phrase in phrases if phrase in clean)
              for stage, phrases in STAGES.items()}
    stage = max(scores, key=scores.get)
    return (stage if scores[stage] else "unknown",
            sorted({phrase for phrase in STAGES.get(stage, ()) if phrase in clean}))

def suggest(stage: str) -> list[dict]:
    suggestions = {
        "lobby": [("social", "Observe player conversations and game start cues")],
        "tasks": [("navigation", "Identify routes and visible task markers"),
                  ("interaction", "Locate the task interaction target")],
        "meeting": [("social", "Listen for meeting discussion without automatically speaking")],
        "voting": [("interaction", "Identify voting UI without selecting anyone")],
        "result": [("memory", "Review result and update learned stage transitions")],
    }
    return [{"category": category, "description": description, "execute": False}
            for category, description in suggestions.get(stage, [])]

class AmongUsObserver:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.records: list[dict] = []
        self._load()

    def _load(self) -> None:
        if not self.path.is_file():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if data.get("world") == WORLD and isinstance(data.get("observations"), list):
                self.records = [row for row in data["observations"][-MAX_OBSERVATIONS:]
                                if isinstance(row, dict) and row.get("stage") in
                                (*STAGES.keys(), "unknown")]
        except (OSError, ValueError, TypeError):
            self.records = []

    def observe(self, frame: dict, *, world_confirmed: bool = False) -> dict:
        if not world_confirmed:
            return {"ok": False, "reason": "Among Us world not confirmed"}
        if not isinstance(frame, dict) or frame.get("ok") is not True:
            return {"ok": False, "reason": "No valid approved-window capture"}
        title = str(frame.get("window_title") or "")
        if "vrchat" not in title.lower():
            return {"ok": False, "reason": "VRChat foreground window required"}
        text = str(frame.get("ocr") or "")[:MAX_TEXT]
        stage, cues = detect_stage(text)
        row = {"epoch": time.time(), "stage": stage, "cues": cues,
               "scene_hash": str(frame.get("scene_hash") or "")[:40],
               "text_excerpt": text[:300], "world": WORLD}
        self.records.append(row)
        self.records = self.records[-MAX_OBSERVATIONS:]
        self._save()
        return {"ok": True, "mode": "observe", "world": WORLD,
                "stage": stage, "cues": cues, "suggestions": suggest(stage),
                "samples": len(self.records), "actions_executed": 0}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({"version": 1, "world": WORLD,
                              "observations": self.records}, indent=2)
        # Replace atomically to avoid destroying prior learning on interruption.
        fd, temp = tempfile.mkstemp(prefix=".amongus-", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(payload)
            os.replace(temp, self.path)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)

    def summary(self):
        counts: dict[str, int] = {}
        for row in self.records:
            stage = row["stage"]
            counts[stage] = counts.get(stage, 0) + 1
        return {"world": WORLD, "mode": "observe", "samples": len(self.records),
                "stage_counts": counts, "actions_executed": 0}
