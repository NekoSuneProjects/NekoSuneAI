"""Local MQTT/Home Assistant device registry and natural device controls.

Discovery and state stay local.  The language model never receives broker
credentials and never publishes arbitrary topics: commands are resolved to a
persisted, discovered device and its declared command topic first.
"""
from __future__ import annotations

import json
import math
import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Callable


Publish = Callable[[str, str, bool], None]
Notify = Callable[[str, str], None]
EventCallback = Callable[[str, dict[str, Any]], None]

SUPPORTED_COMPONENTS = {"light", "switch", "fan", "cover", "lock", "climate", "sensor", "binary_sensor"}
READ_ONLY_COMPONENTS = {"sensor", "binary_sensor"}
SENSITIVE_ACTIONS = {"unlock", "open", "disarm"}


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9_-]+", "-", value.strip().lower()).strip("-")


class SmartHomeManager:
    def __init__(
        self,
        publish: Publish,
        notify: Notify | None = None,
        storage_path: str | Path | None = None,
        electricity_price_per_kwh: float | None = None,
        event_callback: EventCallback | None = None,
    ) -> None:
        self.publish = publish
        self.notify = notify or (lambda _message, _level: None)
        self.event_callback = event_callback or (lambda _event, _context: None)
        self.storage_path = Path(storage_path or os.getenv("SMART_HOME_DEVICES_FILE", "data/smart_home_devices.json"))
        self.electricity_price = max(
            0.0,
            float(
                electricity_price_per_kwh
                if electricity_price_per_kwh is not None
                else os.getenv("ELECTRICITY_PRICE_PER_KWH", "0.25")
            ),
        )
        self._lock = threading.RLock()
        self._devices: dict[str, dict[str, Any]] = {}
        self._topic_index: dict[str, set[str]] = {}
        self._load()

    def _load(self) -> None:
        try:
            raw = json.loads(self.storage_path.read_text("utf-8"))
            rows = raw.get("devices", []) if isinstance(raw, dict) else []
            self._devices = {str(row["id"]): row for row in rows if isinstance(row, dict) and row.get("id")}
        except Exception:
            self._devices = {}
        self._reindex()

    def _save(self) -> None:
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.storage_path.with_suffix(self.storage_path.suffix + ".tmp")
        tmp.write_text(json.dumps({"devices": list(self._devices.values())}, indent=2, sort_keys=True), "utf-8")
        tmp.replace(self.storage_path)

    def _reindex(self) -> None:
        self._topic_index = {}
        for device_id, device in self._devices.items():
            for field in ("state_topic", "json_attributes_topic", "availability_topic"):
                topic = str(device.get(field) or "")
                if topic:
                    self._topic_index.setdefault(topic, set()).add(device_id)

    @staticmethod
    def _expand_topic(value: Any, discovery_topic: str, base_topic: str = "") -> str:
        topic = str(value or "").strip()
        if not topic:
            return ""
        # Home Assistant discovery permits ~ as a base-topic placeholder.
        if topic == "~":
            return base_topic or discovery_topic.rsplit("/", 1)[0]
        if topic.startswith("~/"):
            return (base_topic or discovery_topic.rsplit("/", 1)[0]) + topic[1:]
        return topic

    def discover(self, topic: str, payload: str | bytes) -> dict[str, Any] | None:
        """Ingest HA or Neko generic MQTT discovery configuration."""
        parts = str(topic).strip("/").split("/")
        if not parts or parts[-1] != "config":
            return None
        generic = len(parts) >= 4 and parts[0] == "nekosuneai" and parts[1] == "devices"
        ha = len(parts) >= 4 and parts[0] == "homeassistant" and parts[1] in SUPPORTED_COMPONENTS
        if not (generic or ha):
            return None
        raw_payload = payload.decode("utf-8", "replace") if isinstance(payload, bytes) else str(payload)
        if not raw_payload.strip():
            with self._lock:
                removed = [device_id for device_id, row in self._devices.items() if row.get("discovery_topic") == topic]
                for device_id in removed:
                    self._devices.pop(device_id, None)
                if removed:
                    self._reindex()
                    self._save()
            return None
        try:
            config = json.loads(raw_payload)
        except (TypeError, ValueError):
            return None
        if not isinstance(config, dict):
            return None
        if str(config.get("unique_id") or "").startswith("nekosuneai_"):
            return None
        component = str(config.get("component") or (parts[1] if ha else config.get("type")) or "switch").lower()
        if component not in SUPPORTED_COMPONENTS:
            return None
        object_id = str(config.get("unique_id") or config.get("object_id") or (parts[-2] if len(parts) >= 2 else ""))
        device_id = _slug(object_id)
        if not device_id:
            return None
        device_meta = config.get("device") if isinstance(config.get("device"), dict) else {}
        name = str(config.get("name") or device_meta.get("name") or object_id).strip()[:100]
        room = str(config.get("room") or config.get("area") or "").strip()[:80]
        base_topic = str(config.get("~") or "").rstrip("/")
        command_topic = self._expand_topic(config.get("command_topic") or config.get("cmd_t"), topic, base_topic)
        state_topic = self._expand_topic(config.get("state_topic") or config.get("stat_t"), topic, base_topic)
        attributes_topic = self._expand_topic(config.get("json_attributes_topic") or config.get("json_attr_t"), topic, base_topic)
        availability_topic = self._expand_topic(config.get("availability_topic") or config.get("avty_t"), topic, base_topic)
        aliases = config.get("aliases") if isinstance(config.get("aliases"), list) else []
        now = time.time()
        with self._lock:
            old = self._devices.get(device_id, {})
            row = {
                **old,
                "id": device_id,
                "name": name,
                "component": component,
                "room": room or str(old.get("room") or ""),
                "aliases": sorted({str(x).strip().lower() for x in [*old.get("aliases", []), *aliases] if str(x).strip()}),
                "command_topic": command_topic,
                "state_topic": state_topic,
                "json_attributes_topic": attributes_topic,
                "availability_topic": availability_topic,
                "payload_on": str(config.get("payload_on", "ON")),
                "payload_off": str(config.get("payload_off", "OFF")),
                "value_template": str(config.get("value_template") or ""),
                "brightness_scale": max(1, int(config.get("brightness_scale", 255) or 255)),
                "brightness_command_topic": self._expand_topic(config.get("brightness_command_topic") or config.get("bri_cmd_t"), topic, base_topic),
                "discovery_topic": topic,
                "discovered_epoch": float(old.get("discovered_epoch") or now),
                "last_seen_epoch": float(old.get("last_seen_epoch") or 0),
                "available": old.get("available"),
                "state": dict(old.get("state") or {}),
                "battery_history": list(old.get("battery_history") or [])[-48:],
                "power_history": list(old.get("power_history") or [])[-96:],
                "last_battery_warning_epoch": float(old.get("last_battery_warning_epoch") or 0),
                "last_energy_warning_epoch": float(old.get("last_energy_warning_epoch") or 0),
            }
            self._devices[device_id] = row
            self._reindex()
            self._save()
            return self.public(row)

    def subscribed_topics(self) -> list[str]:
        with self._lock:
            return sorted(self._topic_index)

    def ingest(self, topic: str, payload: str | bytes, now: float | None = None) -> list[dict[str, Any]]:
        discovered = self.discover(topic, payload)
        if discovered:
            return [discovered]
        current = time.time() if now is None else float(now)
        raw = payload.decode("utf-8", "replace") if isinstance(payload, bytes) else str(payload)
        try:
            decoded: Any = json.loads(raw)
        except ValueError:
            decoded = raw
        changed: list[dict[str, Any]] = []
        with self._lock:
            for device_id in self._topic_index.get(topic, set()):
                device = self._devices[device_id]
                device["last_seen_epoch"] = current
                if topic == device.get("availability_topic"):
                    device["available"] = raw.strip().lower() not in {"offline", "unavailable", "0", "false"}
                else:
                    state = device.setdefault("state", {})
                    if isinstance(decoded, dict):
                        state.update(decoded)
                    else:
                        state["value"] = decoded
                    self._record_telemetry(device, current)
                changed.append(self.public(device))
            if changed:
                self._save()
        for device in changed:
            try:
                self.event_callback(
                    f"smart_home.{device['id']}.state",
                    {"smart_home": {device["id"]: device}, "device": device},
                )
                self.event_callback("smart_home.state", {"device": device})
            except Exception:
                pass
        return changed

    @staticmethod
    def _number(state: dict[str, Any], *keys: str) -> float | None:
        for key in keys:
            value = state.get(key)
            try:
                if value is not None and value != "":
                    return float(value)
            except (TypeError, ValueError):
                pass
        return None

    def _record_telemetry(self, device: dict[str, Any], now: float) -> None:
        state = dict(device.get("state") or {})
        battery = self._number(state, "battery", "battery_percent", "battery_level")
        if battery is not None:
            history = device.setdefault("battery_history", [])
            if not history or now - float(history[-1][0]) >= 1800 or abs(battery - float(history[-1][1])) >= 1:
                history.append([now, max(0.0, min(100.0, battery))])
                del history[:-48]
            prediction = self.battery_prediction(device)
            if battery <= 15 and now - float(device.get("last_battery_warning_epoch", 0)) >= 21600:
                detail = f"; estimated {prediction['hours_to_critical']:.1f} hours to 5%" if prediction.get("hours_to_critical") is not None else ""
                self.notify(f"{device.get('name', 'Device')} battery is low at {battery:.0f}%{detail}.", "warning")
                device["last_battery_warning_epoch"] = now
        power = self._number(state, "power_w", "power", "watts")
        if power is not None and power >= 0:
            history = device.setdefault("power_history", [])
            previous = [float(x[1]) for x in history[-24:] if isinstance(x, list) and len(x) == 2]
            if len(previous) >= 6:
                average = sum(previous) / len(previous)
                deviation = math.sqrt(sum((x - average) ** 2 for x in previous) / len(previous))
                threshold = max(average * 1.75, average + 3 * deviation, 25.0)
                if power > threshold and now - float(device.get("last_energy_warning_epoch", 0)) >= 21600:
                    self.notify(
                        f"{device.get('name', 'Device')} is using an unusual {power:.0f} W (recent average {average:.0f} W).",
                        "warning",
                    )
                    device["last_energy_warning_epoch"] = now
            history.append([now, power])
            del history[:-96]

    @staticmethod
    def battery_prediction(device: dict[str, Any]) -> dict[str, float | None]:
        history = [x for x in device.get("battery_history", []) if isinstance(x, list) and len(x) == 2]
        if len(history) < 2:
            return {"hours_to_critical": None, "percent_per_hour": None}
        first, last = history[0], history[-1]
        hours = (float(last[0]) - float(first[0])) / 3600.0
        if hours < 0.25:
            return {"hours_to_critical": None, "percent_per_hour": None}
        rate = (float(last[1]) - float(first[1])) / hours
        if rate >= -0.05:
            return {"hours_to_critical": None, "percent_per_hour": rate}
        remaining = max(0.0, (float(last[1]) - 5.0) / -rate)
        return {"hours_to_critical": remaining, "percent_per_hour": rate}

    def set_aliases(self, device_id: str, aliases: list[str], room: str | None = None) -> dict[str, Any]:
        with self._lock:
            device = self._devices.get(str(device_id))
            if not device:
                raise ValueError("smart-home device was not found")
            device["aliases"] = sorted({_slug(x).replace("-", " ") for x in aliases if _slug(x)})[:30]
            if room is not None:
                device["room"] = str(room).strip()[:80]
            self._save()
            return self.public(device)

    def resolve(self, description: str, room: str | None = None) -> dict[str, Any]:
        wanted = re.sub(r"^the\s+", "", " ".join(str(description).lower().split())).strip()
        room_value = " ".join(str(room or "").lower().split())
        generic = wanted in {"light", "lights", "lamp", "switch", "device"}
        with self._lock:
            candidates: list[tuple[int, dict[str, Any]]] = []
            for device in self._devices.values():
                device_room = " ".join(str(device.get("room") or "").lower().split())
                if generic and room_value and device_room != room_value:
                    continue
                names = {str(device.get("name") or "").lower(), str(device.get("id") or "").replace("-", " ")}
                names.update(str(x).lower() for x in device.get("aliases", []))
                component = str(device.get("component") or "")
                score = 0
                if wanted in names:
                    score = 100
                elif any(name and (wanted in name or name in wanted) for name in names):
                    score = 70
                elif wanted in {"light", "lights", "lamp"} and component == "light":
                    score = 50
                elif wanted in {"switch", "device"} and component == "switch":
                    score = 40
                if score and room_value and device_room == room_value:
                    score += 20
                if score:
                    candidates.append((score, device))
            if not candidates:
                raise ValueError(f"I couldn't find a smart-home device matching {description}.")
            candidates.sort(key=lambda item: item[0], reverse=True)
            best = [item for item in candidates if item[0] == candidates[0][0]]
            if len(best) != 1:
                names = ", ".join(str(item[1].get("name")) for item in best[:5])
                raise ValueError(f"That device name is ambiguous: {names}.")
            return best[0][1]

    def command(self, device_id: str, action: str, value: Any = None, *, confirmed: bool = False) -> str:
        action = str(action).strip().lower()
        with self._lock:
            device = self._devices.get(str(device_id))
            if not device:
                raise ValueError("smart-home device was not found")
            if device.get("component") in READ_ONLY_COMPONENTS or not device.get("command_topic"):
                raise ValueError(f"{device.get('name')} is read-only")
            if action in SENSITIVE_ACTIONS and not confirmed:
                raise PermissionError(f"{action} requires explicit confirmation")
            topic = str(device["command_topic"])
            if action == "on":
                payload = str(device.get("payload_on", "ON"))
            elif action == "off":
                payload = str(device.get("payload_off", "OFF"))
            elif action == "brightness":
                percent = max(0, min(100, int(value)))
                scale = int(device.get("brightness_scale", 255))
                payload = str(round(percent * scale / 100))
                topic = str(device.get("brightness_command_topic") or topic)
            elif action in {"lock", "unlock", "open", "close"}:
                payload = action.upper()
            else:
                raise ValueError(f"unsupported smart-home action: {action}")
            self.publish(topic, payload, False)
            return f"Sent {action} to {device.get('name')}."

    def handle(self, text: str, room: str | None = None) -> str | None:
        cleaned = " ".join(text.strip().lower().split())
        state_match = re.match(r"^(?:what(?:'s| is)|show|check) (?:the )?(.+?) (?:status|state|battery|power|energy)[?]?$", cleaned)
        if state_match:
            device = self.resolve(state_match.group(1), room)
            state = dict(device.get("state") or {})
            prediction = self.battery_prediction(device)
            parts = [f"{device.get('name')} is {'online' if device.get('online') else 'offline'}"]
            battery = self._number(state, "battery", "battery_percent", "battery_level")
            power = self._number(state, "power_w", "power", "watts")
            energy = self._number(state, "energy_kwh", "energy", "total_kwh")
            if battery is not None:
                parts.append(f"battery {battery:.0f}%")
            if prediction.get("hours_to_critical") is not None:
                parts.append(f"about {prediction['hours_to_critical']:.1f} hours to 5% at the recent rate")
            if power is not None:
                parts.append(f"using {power:.0f} watts")
            if energy is not None:
                parts.append(f"recorded {energy:.2f} kWh, estimated cost £{energy * self.electricity_price:.2f}")
            value = state.get("value")
            if value not in (None, ""):
                parts.append(f"state {value}")
            return "; ".join(parts) + "."
        brightness = re.match(r"^(?:set|dim) (?:the )?(.+?)(?: brightness)? (?:to )?(\d{1,3})%?$", cleaned)
        if brightness:
            device = self.resolve(brightness.group(1), room)
            return self.command(str(device["id"]), "brightness", int(brightness.group(2)))
        switch = re.match(r"^(?:turn|switch) (?:the )?(.+?) (on|off)$", cleaned)
        if switch:
            device = self.resolve(switch.group(1), room)
            return self.command(str(device["id"]), switch.group(2))
        switch_first = re.match(r"^(?:turn|switch) (on|off) (?:the )?(.+)$", cleaned)
        if switch_first:
            device = self.resolve(switch_first.group(2), room)
            return self.command(str(device["id"]), switch_first.group(1))
        return None

    def list_devices(self) -> list[dict[str, Any]]:
        with self._lock:
            return [self.public(x) for x in self._devices.values()]

    def public(self, device: dict[str, Any]) -> dict[str, Any]:
        result = {key: value for key, value in device.items() if key not in {"battery_history", "power_history"}}
        last_seen = float(device.get("last_seen_epoch") or 0)
        available = device.get("available")
        result["online"] = bool(last_seen and time.time() - last_seen < 180 and available is not False)
        result["battery_prediction"] = self.battery_prediction(device)
        energy = self._number(dict(device.get("state") or {}), "energy_kwh", "energy", "total_kwh")
        result["estimated_energy_cost"] = energy * self.electricity_price if energy is not None else None
        return result
