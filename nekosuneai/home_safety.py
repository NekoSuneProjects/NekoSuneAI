"""Deterministic local emergency classification for discovered home sensors."""
from __future__ import annotations

import threading
from typing import Any, Callable

from .home_events import HomeEventTimeline


Notify = Callable[[str, str], None]

HAZARDS = {
    "smoke": ("smoke", "Smoke detected"),
    "carbon_monoxide": ("carbon monoxide", "Carbon monoxide detected"),
    "gas": ("gas", "Gas detected"),
    "moisture": ("water leak", "Water leak detected"),
    "safety": ("security", "Security sensor triggered"),
}
ACTIVE = {"on", "true", "1", "yes", "detected", "alarm", "unsafe", "wet", "open"}
CLEAR = {"off", "false", "0", "no", "clear", "safe", "dry", "closed"}


class HomeSafetyManager:
    def __init__(self, notify: Notify, timeline: HomeEventTimeline) -> None:
        self.notify = notify
        self.timeline = timeline
        self._lock = threading.RLock()
        self._active: set[str] = set()

    @staticmethod
    def _hazard(device: dict[str, Any]) -> tuple[str, str] | None:
        device_class = str(device.get("device_class") or "").strip().lower()
        if device_class in HAZARDS:
            return HAZARDS[device_class]
        name = str(device.get("name") or "").lower()
        for key, value in HAZARDS.items():
            if key.replace("_", " ") in name:
                return value
        if any(word in name for word in ("water leak", "leak sensor", "flood sensor")):
            return HAZARDS["moisture"]
        if any(word in name for word in ("security alarm", "burglar alarm", "intrusion")):
            return HAZARDS["safety"]
        return None

    @staticmethod
    def _active_state(device: dict[str, Any]) -> bool | None:
        state = dict(device.get("state") or {})
        raw = state.get("alarm", state.get("detected", state.get("value")))
        if raw is None:
            for key in ("smoke", "carbon_monoxide", "gas", "moisture", "water_leak", "security"):
                if key in state:
                    raw = state[key]
                    break
        if isinstance(raw, bool):
            return raw
        normalized = str(raw).strip().lower()
        if normalized in ACTIVE:
            return True
        if normalized in CLEAR:
            return False
        return None

    def ingest(self, device: dict[str, Any]) -> dict[str, Any] | None:
        hazard = self._hazard(device)
        active = self._active_state(device)
        if hazard is None or active is None:
            return None
        kind, headline = hazard
        device_id = str(device.get("id") or device.get("name") or "sensor")
        room = str(device.get("room") or "unknown room")
        incident_key = f"{device_id}:{kind}"
        with self._lock:
            was_active = incident_key in self._active
            if active:
                self._active.add(incident_key)
            else:
                self._active.discard(incident_key)
        if active and not was_active:
            message = f"DANGER: {headline} in {room}. Check the area and follow your emergency plan now."
            self.timeline.record("safety", f"{kind}.active", message, room=room, source=device_id, severity="danger")
            self.notify(message, "danger")
            return {"status": "active", "hazard": kind, "message": message}
        if not active and was_active:
            message = f"{headline} sensor in {room} now reports clear. Verify the area is actually safe."
            self.timeline.record("safety", f"{kind}.clear", message, room=room, source=device_id, severity="warning")
            self.notify(message, "warning")
            return {"status": "clear", "hazard": kind, "message": message}
        return None

    def active_incidents(self) -> list[str]:
        with self._lock:
            return sorted(self._active)
