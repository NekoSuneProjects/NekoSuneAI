from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AndroidDevice:
    device_id: str
    name: str = "Android phone"
    last_seen: float = field(default_factory=time.time)
    telemetry: dict[str, Any] = field(default_factory=dict)
    notifications: list[dict[str, Any]] = field(default_factory=list)
    commands: list[dict[str, Any]] = field(default_factory=list)
    next_command_id: int = 1


class AndroidDeviceHub:
    """Small in-memory hub for trusted Android companion devices.

    The Android app maintains one long-poll request instead of rapid polling.
    This keeps CPU usage and radio wakeups low while still allowing commands
    such as FIND_PHONE to arrive quickly.
    """

    def __init__(self) -> None:
        self._devices: dict[str, AndroidDevice] = {}
        self._lock = threading.RLock()
        self._changed = threading.Condition(self._lock)

    def _get(self, device_id: str) -> AndroidDevice:
        key = device_id.strip()
        if not key:
            raise ValueError("device_id is required")
        device = self._devices.get(key)
        if device is None:
            device = AndroidDevice(device_id=key)
            self._devices[key] = device
        return device

    def heartbeat(self, device_id: str, name: str, telemetry: dict[str, Any]) -> dict[str, Any]:
        with self._changed:
            device = self._get(device_id)
            device.name = (name or device.name)[:80]
            device.last_seen = time.time()
            device.telemetry = dict(telemetry or {})
            self._changed.notify_all()
            return self.snapshot(device)

    def add_notification(self, device_id: str, payload: dict[str, Any]) -> None:
        with self._changed:
            device = self._get(device_id)
            device.last_seen = time.time()
            item = dict(payload or {})
            item["received_at"] = time.time()
            device.notifications.append(item)
            if len(device.notifications) > 100:
                del device.notifications[:-100]
            self._changed.notify_all()

    def enqueue(self, device_id: str, command: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
        with self._changed:
            device = self._get(device_id)
            item = {
                "id": device.next_command_id,
                "command": str(command).upper(),
                "args": dict(args or {}),
                "created_at": time.time(),
            }
            device.next_command_id += 1
            device.commands.append(item)
            if len(device.commands) > 50:
                del device.commands[:-50]
            self._changed.notify_all()
            return item

    def wait_commands(self, device_id: str, after: int, wait_seconds: float = 25.0) -> list[dict[str, Any]]:
        deadline = time.monotonic() + max(0.0, min(float(wait_seconds), 30.0))
        with self._changed:
            device = self._get(device_id)
            while True:
                device.last_seen = time.time()
                pending = [c for c in device.commands if int(c.get("id", 0)) > int(after)]
                if pending:
                    return pending
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return []
                self._changed.wait(timeout=remaining)

    def list_devices(self) -> list[dict[str, Any]]:
        with self._lock:
            return [self.snapshot(d) for d in self._devices.values()]

    def latest_notifications(self, device_id: str, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            device = self._get(device_id)
            return list(device.notifications[-max(1, min(int(limit), 100)):])

    @staticmethod
    def snapshot(device: AndroidDevice) -> dict[str, Any]:
        return {
            "device_id": device.device_id,
            "name": device.name,
            "last_seen": device.last_seen,
            "online": (time.time() - device.last_seen) < 90,
            "telemetry": dict(device.telemetry),
        }
