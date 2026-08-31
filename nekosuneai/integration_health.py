from __future__ import annotations

import importlib.util
import os
import time
from typing import Any


SEVERITY = {"healthy": 0, "disabled": 0, "degraded": 1, "unavailable": 2}


def _item(name: str, status: str, detail: str) -> dict[str, str]:
    return {"name": name, "status": status, "detail": detail}


def _installed(module: str) -> bool:
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


def build_health_snapshot(config: Any, *, home_connected: bool = False, voice_enabled: bool | None = None) -> dict[str, Any]:
    """Build a fast local snapshot; never performs network requests."""
    items: list[dict[str, str]] = []
    voice_enabled = bool(getattr(config, "voice_enabled", False)) if voice_enabled is None else voice_enabled

    tts_provider = str(getattr(config, "tts_provider", "") or "xtts")
    if not voice_enabled:
        items.append(_item("Voice output", "disabled", "Voice replies are off"))
    elif tts_provider == "bridge":
        bridge_url = str(getattr(config, "bridge_ws_url", "") or "")
        items.append(_item("Voice output", "healthy" if bridge_url else "unavailable", "Bridge configured" if bridge_url else "Bridge TTS selected but BRIDGE_WS_URL is missing"))
    elif tts_provider == "xtts":
        items.append(_item("Voice output", "healthy" if _installed("TTS") else "unavailable", "Local XTTS package available" if _installed("TTS") else "Install the voice requirements to use local XTTS"))
    else:
        items.append(_item("Voice output", "healthy", f"{tts_provider} configured"))

    stt_ready = _installed("sounddevice")
    items.append(_item("Voice input", "healthy" if voice_enabled and stt_ready else "unavailable" if voice_enabled else "disabled", "Microphone dependencies available" if stt_ready else "Voice is off" if not voice_enabled else "sounddevice is not installed"))

    mqtt_host = str(getattr(config, "home_assistant_mqtt_host", "") or "")
    items.append(_item("Home Assistant", "healthy" if mqtt_host and home_connected else "degraded" if mqtt_host else "disabled", "MQTT connected" if mqtt_host and home_connected else "MQTT configured but not connected" if mqtt_host else "No MQTT host configured"))

    mcp_enabled = bool(getattr(config, "mcp_enabled", False))
    servers = str(getattr(config, "mcp_servers_json", "") or "[]").strip()
    items.append(_item("MCP tools", "healthy" if mcp_enabled and servers not in {"", "[]"} else "unavailable" if mcp_enabled else "disabled", "Server configuration present" if mcp_enabled and servers not in {"", "[]"} else "MCP enabled without a server" if mcp_enabled else "MCP is disabled"))

    mobile_enabled = os.getenv("MOBILE_NOTIFY_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
    mobile_topic = os.getenv("MOBILE_NOTIFY_TOPIC", "").strip()
    items.append(_item("Mobile notifications", "degraded" if mobile_enabled and mobile_topic else "unavailable" if mobile_enabled else "disabled", "Configured; delivery is verified when a notification is sent" if mobile_enabled and mobile_topic else "Enabled without MOBILE_NOTIFY_TOPIC" if mobile_enabled else "Mobile notifications are disabled"))

    bluetooth_enabled = bool(getattr(config, "bluetooth_reconnect_enabled", False))
    items.append(_item("Bluetooth audio", "degraded" if bluetooth_enabled else "disabled", "Reconnect watchdog configured; live device state is checked separately" if bluetooth_enabled else "Bluetooth reconnect is disabled"))

    problems = sum(1 for row in items if SEVERITY[row["status"]] > 0)
    overall = "unavailable" if any(row["status"] == "unavailable" for row in items) else "degraded" if problems else "healthy"
    return {"overall": overall, "problem_count": problems, "checked_epoch": time.time(), "items": items}


def append_runtime_item(snapshot: dict[str, Any], name: str, status: str, detail: str) -> dict[str, Any]:
    snapshot.setdefault("items", []).append(_item(name, status, detail))
    snapshot["problem_count"] = sum(1 for row in snapshot["items"] if SEVERITY.get(row["status"], 2) > 0)
    snapshot["overall"] = "unavailable" if any(row["status"] == "unavailable" for row in snapshot["items"]) else "degraded" if snapshot["problem_count"] else "healthy"
    return snapshot
