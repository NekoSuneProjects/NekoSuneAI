"""Persistent recurring MCP monitors for aircraft, weather and alerts."""
from __future__ import annotations

import hashlib
import json
import re
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from .config import Config
from .database import get_state, set_state
from .mcp_client import call_first_available, route_tool

STATE_KEY = "mcp_monitors_v1"

PRIVATE_MONITOR_NAMES = {
    "aircraft_nearby": "Aircraft nearby",
    "military_aircraft_nearby": "Military aircraft nearby",
    "weather_now": "Weather forecast",
    "weather_forecast": "Weather forecast",
    "weather_warnings": "Weather warnings",
    "emergency_alerts": "Government emergency alerts",
}


def _private_monitor_name(tool: str) -> str:
    return PRIVATE_MONITOR_NAMES.get(tool, "Scheduled monitor")


@dataclass
class Monitor:
    id: str
    name: str
    tool: str
    arguments: dict[str, Any]
    interval_seconds: int
    active: bool = True
    last_hash: str = ""
    last_run: str = ""
    next_run_epoch: float = 0


def _load() -> list[Monitor]:
    try:
        rows = json.loads(get_state(STATE_KEY, "[]"))
        return [Monitor(**row) for row in rows if isinstance(row, dict)]
    except (ValueError, TypeError):
        return []


def _save(items: list[Monitor]) -> None:
    set_state(STATE_KEY, json.dumps([asdict(item) for item in items], ensure_ascii=False))


def parse_monitor_request(text: str) -> tuple[str, Any] | None:
    lowered = text.lower().strip()
    if re.search(r"\b(?:stop|cancel|delete|remove|clear|purge)\s+(?:all\s+)?(?:monitoring|monitors|tracking|scheduled (?:tasks?|monitors?|updates?)|updates?)\b", lowered):
        return "stop_all", None
    match = re.search(r"\b(?:stop|cancel|delete|remove)\s+(?:monitor|task)\s+([\w-]+)", lowered)
    if match:
        return "stop", match.group(1)
    if re.search(r"\b(?:list|show|what are)\b.*\b(?:monitors|scheduled tasks?|tracking)\b", lowered):
        return "list", None
    scheduling = any(phrase in lowered for phrase in (
        "keep me posted", "keep me updated", "monitor ", "track ", "every ", "until i tell", "schedule ",
    ))
    if not scheduling:
        return None
    routed = route_tool(text)
    if not routed:
        return None
    interval = 300
    interval_match = re.search(r"\bevery\s+(\d+)\s*(seconds?|secs?|minutes?|mins?|hours?|hrs?)", lowered)
    if interval_match:
        count = max(1, int(interval_match.group(1)))
        unit = interval_match.group(2)
        interval = count * (3600 if unit.startswith(("hour", "hr")) else 60 if unit.startswith(("minute", "min")) else 1)
    interval = max(30, interval)
    tool, arguments = routed
    # The location stays only in private tool arguments. Never copy it into the
    # monitor name because names are shown in chat and the dashboard.
    return "create", Monitor(id=uuid.uuid4().hex[:8], name=_private_monitor_name(tool), tool=tool,
                              arguments=arguments, interval_seconds=interval, next_run_epoch=0)


def _walk_alerts(value: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(value, dict):
        if any(key in value for key in ("headline", "event", "title", "severity", "instruction", "description")):
            found.append(value)
        for child in value.values(): found.extend(_walk_alerts(child))
    elif isinstance(value, list):
        for child in value: found.extend(_walk_alerts(child))
    return found


def _emergency_summary(monitor: Monitor, payload: Any) -> str | None:
    if monitor.tool not in {"emergency_alerts", "emergency_broadcasts", "weather_warnings", "tornado_tracker"}:
        return None
    alerts = _walk_alerts(payload)
    if not alerts:
        return f"Government emergency update [{monitor.id}]: no active alerts were returned for the selected area."
    lines: list[str] = []
    seen: set[str] = set()
    for alert in alerts[:5]:
        headline = str(alert.get("headline") or alert.get("event") or alert.get("title") or "Official alert").strip()
        detail = str(alert.get("instruction") or alert.get("description") or alert.get("areaDesc") or "").strip()
        severity = str(alert.get("severity") or alert.get("urgency") or "").strip()
        line = ". ".join(part for part in (headline, f"Severity {severity}" if severity else "", detail[:500]) if part)
        if line and line not in seen: seen.add(line); lines.append(line)
    return f"Government emergency broadcast [{monitor.id}]. " + " ".join(lines)


def _unwrap_payload(result: Any) -> Any:
    """Return useful structured data from nested MCP transport wrappers."""
    payload = result
    for _ in range(4):
        if isinstance(payload, dict) and payload.get("structuredContent") is not None:
            payload = payload["structuredContent"]
            continue
        content = payload.get("content") if isinstance(payload, dict) else None
        if isinstance(content, list):
            text = next((str(item.get("text", "")) for item in content if isinstance(item, dict) and item.get("type") == "text"), "")
            if text:
                try:
                    payload = json.loads(text)
                    continue
                except ValueError:
                    return text
        break
    return payload


def _weather_alert_level(tool: str, result: Any) -> str:
    """Classify forecast urgency without treating ordinary weather as danger."""
    if tool not in {"weather_now", "weather_forecast", "rain_eta", "weather_warnings"}:
        return "none"
    payload = _unwrap_payload(result)
    if not isinstance(payload, dict):
        return "none"
    lowered = json.dumps(payload, ensure_ascii=False, default=str).lower()
    if any(word in lowered for word in ("extreme", "severe", "tornado warning", "immediate threat")):
        return "danger"
    rain = payload.get("rain") if isinstance(payload.get("rain"), dict) else {}
    eta = rain.get("rainEtaMinutes")
    currently_wet = bool(rain.get("currentlyWet"))
    lightning = payload.get("lightning") if isinstance(payload.get("lightning"), dict) else {}
    lightning_risk = str(lightning.get("risk") or "").lower()
    if currently_wet or (isinstance(eta, (int, float)) and 0 <= eta <= 15):
        return "warning"
    if lightning_risk and lightning_risk != "low":
        return "warning"
    if any(word in lowered for word in ("warning", "alert", "hazard")):
        return "warning"
    return "none"


def _summary(monitor: Monitor, result: dict[str, Any]) -> str:
    payload = _unwrap_payload(result)
    emergency = _emergency_summary(monitor, payload)
    if emergency:
        return emergency
    if isinstance(payload, str):
        return f"Scheduled update [{monitor.id}]: {payload[:1800]}"
    if monitor.tool in {"aircraft_nearby", "military_aircraft_nearby"} and isinstance(payload, dict):
        aircraft = payload.get("aircraft") if isinstance(payload.get("aircraft"), list) else []
        count = int(payload.get("count", len(aircraft)) or 0)
        kind = "military aircraft" if monitor.tool == "military_aircraft_nearby" else "aircraft"
        if not aircraft:
            return f"Scheduled {kind} update [{monitor.id}]: none were detected."
        details = []
        for plane in aircraft[:3]:
            identity = plane.get("callsign") or plane.get("registration") or plane.get("aircraftType") or "unidentified aircraft"
            distance = plane.get("distanceNm")
            movement = plane.get("movement") or plane.get("flightPhase") or ""
            if isinstance(movement, dict):
                movement = movement.get("note") or movement.get("phase") or ""
            details.append(f"{identity}{f', {float(distance):.1f} nautical miles away' if isinstance(distance, (int, float)) else ''}{f', {movement}' if movement else ''}")
        return f"Scheduled {kind} update [{monitor.id}]: {count} detected. " + ". ".join(details) + "."
    if monitor.tool in {"weather_now", "weather_forecast"} and isinstance(payload, dict):
        weather = payload.get("current") if isinstance(payload.get("current"), dict) else payload
        temperature = weather.get("temperature") or weather.get("temperatureC") or weather.get("temp_c")
        condition = weather.get("condition") or weather.get("summary") or weather.get("weather")
        wind = weather.get("windSpeed") or weather.get("windSpeedKph") or weather.get("wind_kph")
        rain = payload.get("rain") if isinstance(payload.get("rain"), dict) else {}
        eta = rain.get("rainEtaMinutes")
        currently_wet = bool(rain.get("currentlyWet"))
        lightning = payload.get("lightning") if isinstance(payload.get("lightning"), dict) else {}
        lightning_risk = str(lightning.get("risk") or "").strip()
        parts = [str(condition).strip() if condition else ""]
        if temperature is not None: parts.append(f"temperature {temperature} degrees Celsius")
        if wind is not None: parts.append(f"wind speed {wind} kilometres per hour")
        if currently_wet:
            parts.insert(0, "Warning: rain is occurring now")
        elif isinstance(eta, (int, float)) and 0 <= eta <= 15:
            parts.insert(0, f"Warning: rain is expected in about {max(1, round(eta))} minutes")
        elif isinstance(eta, (int, float)):
            parts.append(f"rain is expected in about {max(1, round(eta))} minutes")
        if lightning_risk and lightning_risk.lower() != "low":
            parts.append(f"lightning risk is {lightning_risk}")
        spoken = ", ".join(part for part in parts if part)
        return f"Scheduled weather update [{monitor.id}]: {spoken or 'the forecast was refreshed, but no readable conditions were returned.'}"
    if isinstance(payload, dict):
        readable = []
        for key, value in payload.items():
            if key.lower() in {"provider", "reference", "latitude", "longitude", "caveat", "source"}:
                continue
            if isinstance(value, (str, int, float, bool)) and value not in ("", None):
                label = re.sub(r"(?<!^)(?=[A-Z])", " ", key).replace("_", " ")
                readable.append(f"{label} is {value}")
            if len(readable) >= 5:
                break
        if readable:
            return f"Scheduled update [{monitor.id}]: " + "; ".join(readable) + "."
    return f"Scheduled update [{monitor.id}]: the check completed, but it did not return a readable result."


class MonitorManager:
    def __init__(self, config: Config, notify: Callable[[str, str], None]) -> None:
        self.config = config
        self.notify = notify
        self._stop = threading.Event()
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive(): return
        self._thread = threading.Thread(target=self._loop, daemon=True, name="mcp-monitor")
        self._thread.start()

    def handle(self, text: str) -> str | None:
        parsed = parse_monitor_request(text)
        if not parsed: return None
        action, value = parsed
        with self._lock:
            items = _load()
            if action == "create":
                items.append(value); _save(items)
                return f"Scheduled monitor {value.id}: {value.name}, every {value.interval_seconds // 60 or 1} minute(s). I'll keep posting updates until you stop it."
            if action == "stop_all":
                count = len(items)
                _save([]); return f"Removed all {count} scheduled monitor(s)."
            if action == "stop":
                found = next((item for item in items if item.id == value), None)
                if not found: return f"I couldn't find monitor {value}."
                found.active = False; _save(items); return f"Stopped monitor {found.id}: {_private_monitor_name(found.tool)}."
            active = [item for item in items if item.active]
            if not active: return "There are no active scheduled monitors."
            return "Active scheduled monitors:\n" + "\n".join(f"- {x.id}: {_private_monitor_name(x.tool)}, every {x.interval_seconds}s" for x in active)

    def list_all(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = []
            for item in _load():
                row = asdict(item)
                row["name"] = _private_monitor_name(item.tool)
                # Tool arguments may contain the private saved location and are
                # not required by the management page.
                row.pop("arguments", None)
                rows.append(row)
            return rows

    def remove(self, monitor_id: str) -> bool:
        with self._lock:
            items = _load()
            kept = [item for item in items if item.id != str(monitor_id)]
            if len(kept) == len(items):
                return False
            _save(kept)
            return True

    def clear(self) -> int:
        with self._lock:
            items = _load()
            _save([])
            return len(items)

    def _loop(self) -> None:
        while not self._stop.wait(2):
            now = time.time()
            with self._lock:
                items = _load()
                due = [item for item in items if item.active and item.next_run_epoch <= now]
            for item in due:
                level = "none"
                try:
                    result = call_first_available(self.config, item.tool, item.arguments)
                    serialized = json.dumps(result, ensure_ascii=False, sort_keys=True, default=str)
                    digest = hashlib.sha256(serialized.encode()).hexdigest()
                    # Always post the first result, then post changes. Also send
                    # a heartbeat at least hourly so "keep me posted" is literal.
                    elapsed = now - (datetime.fromisoformat(item.last_run).timestamp() if item.last_run else 0)
                    if digest != item.last_hash or elapsed >= 3600:
                        lowered = serialized.lower()
                        level = _weather_alert_level(item.tool, result)
                        if level == "none":
                            level = "danger" if any(x in lowered for x in ("extreme", "severe", "tornado warning", "immediate threat")) else "warning" if any(x in lowered for x in ("warning", "alert", "hazard")) else "none"
                        self.notify(_summary(item, result), level)
                    item.last_hash = digest
                except Exception as exc:
                    self.notify(f"Scheduled monitor [{item.id}] could not update: {exc}", "warning")
                item.last_run = datetime.now(timezone.utc).isoformat()
                item.next_run_epoch = time.time() + item.interval_seconds
                with self._lock:
                    latest = _load()
                    for index, existing in enumerate(latest):
                        if existing.id == item.id: latest[index] = item; break
                    _save(latest)
