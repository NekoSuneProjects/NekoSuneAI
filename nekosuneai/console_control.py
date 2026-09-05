from __future__ import annotations

import json
import os
import re
import shlex
import socket
import subprocess
import time
from dataclasses import dataclass
from typing import Any

import requests

from .database import get_state, set_state

STATE_KEY = "console_control_state_v1"
PS_DISCOVERY_PORT = 987


class ConsoleControlError(RuntimeError):
    pass


def _env(name: str, default: str = "") -> str:
    return str(os.getenv(name, default) or "").strip()


def _truthy(name: str, default: bool = False) -> bool:
    value = _env(name)
    if not value:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def _load_state() -> dict[str, Any]:
    try:
        value = json.loads(get_state(STATE_KEY, "{}"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _save_state(value: dict[str, Any]) -> None:
    try:
        set_state(STATE_KEY, json.dumps(value, ensure_ascii=False))
    except Exception:
        pass


def _remember(platform: str, snapshot: dict[str, Any]) -> dict[str, Any]:
    state = _load_state()
    now = time.time()
    item = dict(snapshot)
    item["checked_at"] = now
    if item.get("online"):
        item["last_seen"] = now
    else:
        previous = state.get(platform) if isinstance(state.get(platform), dict) else {}
        if previous.get("last_seen"):
            item["last_seen"] = previous["last_seen"]
    state[platform] = item
    _save_state(state)
    return item


def _last_snapshot(platform: str) -> dict[str, Any]:
    state = _load_state()
    item = state.get(platform)
    return dict(item) if isinstance(item, dict) else {}


def _run_configured(command: str, *, replacements: dict[str, str] | None = None) -> str:
    if not command.strip():
        raise ConsoleControlError("No local command is configured for that console action.")
    replacements = replacements or {}
    args = shlex.split(command)
    rendered = []
    for arg in args:
        for key, value in replacements.items():
            arg = arg.replace("{" + key + "}", value)
        rendered.append(arg)
    result = subprocess.run(rendered, capture_output=True, text=True, timeout=30, check=False)
    if result.returncode != 0:
        raise ConsoleControlError((result.stderr or result.stdout or "console helper failed").strip()[:900])
    return (result.stdout or "").strip()


def _magic_packet(mac: str) -> None:
    clean = re.sub(r"[^0-9A-Fa-f]", "", mac)
    if len(clean) != 12:
        raise ConsoleControlError("Console MAC address must contain 12 hexadecimal digits.")
    packet = bytes.fromhex("FF" * 6 + clean * 16)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        for port in (9, 7):
            sock.sendto(packet, ("255.255.255.255", port))
    finally:
        sock.close()


def _host_reachable(host: str, ports: tuple[int, ...], timeout: float = 0.35) -> bool:
    host = host.split(":", 1)[0].strip()
    if not host:
        return False
    for port in ports:
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except OSError:
            pass
    return False


def _parse_httpish(payload: bytes) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in payload.decode("utf-8", "ignore").replace("\r", "").split("\n"):
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        result[key.strip().lower()] = value.strip()
    return result


def discover_playstation(timeout: float = 1.2) -> list[dict[str, Any]]:
    """Discover Sony consoles exposing the documented Remote Play discovery service.

    This only sends the LAN discovery request. It does not register, authenticate,
    or bypass Sony account/device pairing.
    """
    version = _env("PS_DISCOVERY_PROTOCOL_VERSION", "00030010")
    request = (
        "SRCH * HTTP/1.1\n"
        f"device-discovery-protocol-version:{version}\n"
    ).encode("ascii", "ignore")
    configured = _env("PS5_HOST")
    targets = [(configured, PS_DISCOVERY_PORT)] if configured else [("255.255.255.255", PS_DISCOVERY_PORT)]
    found: dict[str, dict[str, Any]] = {}
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.settimeout(0.25)
    try:
        for target in targets:
            try:
                sock.sendto(request, target)
            except OSError:
                pass
        deadline = time.monotonic() + max(0.3, timeout)
        while time.monotonic() < deadline:
            try:
                data, address = sock.recvfrom(4096)
            except socket.timeout:
                continue
            fields = _parse_httpish(data)
            host = address[0]
            found[host] = {
                "host": host,
                "name": fields.get("host-name") or fields.get("device-name") or "PlayStation",
                "status_code": fields.get("status-code", ""),
                "status": fields.get("status", ""),
                "system_version": fields.get("system-version", ""),
                "device_type": fields.get("device-type", ""),
                "raw": fields,
            }
    finally:
        sock.close()
    return list(found.values())


@dataclass
class BridgeClient:
    base_url: str
    token: str = ""

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def status(self) -> dict[str, Any]:
        if not self.base_url:
            return {}
        response = requests.get(self.base_url.rstrip("/") + "/status", headers=self._headers(), timeout=4)
        response.raise_for_status()
        value = response.json()
        return value if isinstance(value, dict) else {}

    def command(self, action: str, value: str = "") -> dict[str, Any]:
        if not self.base_url:
            raise ConsoleControlError("No authenticated console bridge is configured.")
        response = requests.post(
            self.base_url.rstrip("/") + "/command",
            headers=self._headers(),
            json={"action": action, "value": value},
            timeout=12,
        )
        response.raise_for_status()
        value_json = response.json() if response.content else {}
        if isinstance(value_json, dict) and value_json.get("ok") is False:
            raise ConsoleControlError(str(value_json.get("error") or value_json.get("message") or "console bridge rejected the command"))
        return value_json if isinstance(value_json, dict) else {"ok": True}


class PlayStationConsole:
    platform = "playstation"

    def __init__(self) -> None:
        self.bridge = BridgeClient(_env("PS_REMOTE_PLAY_BRIDGE_URL"), _env("PS_REMOTE_PLAY_BRIDGE_TOKEN"))

    def capabilities(self) -> dict[str, bool]:
        bridge = bool(self.bridge.base_url)
        return {
            "discovery": True,
            "status": True,
            "wake": bridge or bool(_env("PS_WAKE_COMMAND")),
            "sleep": bridge or bool(_env("PS_REST_COMMAND")),
            "launch": bridge or bool(_env("PS_LAUNCH_COMMAND")),
            "active_title": bridge,
            "remote_play": bridge or bool(_env("PS_REMOTE_PLAY_COMMAND")),
            "media_remote": bridge,
        }

    def status(self) -> dict[str, Any]:
        bridge_status: dict[str, Any] = {}
        bridge_error = ""
        if self.bridge.base_url:
            try:
                bridge_status = self.bridge.status()
            except Exception as exc:
                bridge_error = str(exc)
        devices = discover_playstation(float(_env("PS_DISCOVERY_TIMEOUT", "1.0") or "1.0"))
        online = bool(devices) or bool(bridge_status.get("online"))
        state = str(bridge_status.get("state") or ("online" if online else "offline")).lower()
        if state in {"standby", "rest", "rest-mode", "rest_mode"}:
            state = "rest"
        elif online and state in {"", "unknown", "offline"}:
            state = "online"
        snapshot = {
            "platform": self.platform,
            "name": str(bridge_status.get("name") or (devices[0].get("name") if devices else "PlayStation 5")),
            "online": online,
            "state": state,
            "host": str(bridge_status.get("host") or (devices[0].get("host") if devices else _env("PS5_HOST"))),
            "active_title": str(bridge_status.get("active_title") or bridge_status.get("title") or ""),
            "activity": str(bridge_status.get("activity") or ""),
            "remote_play_available": self.capabilities()["remote_play"],
            "capabilities": self.capabilities(),
            "bridge_error": bridge_error,
        }
        return _remember(self.platform, snapshot)

    def command(self, action: str, value: str = "") -> str:
        aliases = {"power_on": "wake", "rest": "sleep", "rest_mode": "sleep", "playpause": "play_pause"}
        action = aliases.get(action, action)
        if action == "status":
            return format_console_status(self.status())
        if self.bridge.base_url:
            result = self.bridge.command(action, value)
            message = str(result.get("message") or "").strip()
            return message or f"PlayStation {action.replace('_', ' ')} command sent through the authenticated bridge."
        commands = {
            "wake": "PS_WAKE_COMMAND",
            "sleep": "PS_REST_COMMAND",
            "remote_play": "PS_REMOTE_PLAY_COMMAND",
            "launch": "PS_LAUNCH_COMMAND",
        }
        env_name = commands.get(action)
        if env_name and _env(env_name):
            _run_configured(_env(env_name), replacements={"title": value})
            return f"PlayStation {action.replace('_', ' ')} command sent through the configured local helper."
        if action == "launch":
            raise ConsoleControlError("Direct PlayStation game/app launch is unavailable because no authenticated bridge exposing launch is configured.")
        raise ConsoleControlError(f"PlayStation {action.replace('_', ' ')} is unavailable until PS_REMOTE_PLAY_BRIDGE_URL or a supported local helper is configured.")


class XboxConsole:
    platform = "xbox"

    def __init__(self) -> None:
        self.bridge = BridgeClient(_env("XBOX_REMOTE_BRIDGE_URL"), _env("XBOX_REMOTE_BRIDGE_TOKEN"))

    def capabilities(self) -> dict[str, bool]:
        bridge = bool(self.bridge.base_url)
        return {
            "discovery": bridge or bool(_env("XBOX_HOST")),
            "status": bridge or bool(_env("XBOX_HOST")),
            "wake": bridge or bool(_env("XBOX_MAC")) or bool(_env("XBOX_WAKE_COMMAND")),
            "sleep": bridge or bool(_env("XBOX_SLEEP_COMMAND")),
            "shutdown": bridge or bool(_env("XBOX_SHUTDOWN_COMMAND")),
            "restart": bridge or bool(_env("XBOX_RESTART_COMMAND")),
            "launch": bridge or bool(_env("XBOX_LAUNCH_COMMAND")),
            "active_title": bridge,
            "remote_play": bridge or bool(_env("XBOX_REMOTE_PLAY_COMMAND")),
            "media_remote": bridge,
            "controller_status": bridge,
        }

    def status(self) -> dict[str, Any]:
        bridge_status: dict[str, Any] = {}
        bridge_error = ""
        if self.bridge.base_url:
            try:
                bridge_status = self.bridge.status()
            except Exception as exc:
                bridge_error = str(exc)
        host = str(bridge_status.get("host") or _env("XBOX_HOST"))
        # SmartGlass commonly uses UDP 5050, which cannot be tested with a TCP
        # connect. Configured hosts are additionally checked on common local
        # service ports only as a reachability hint; authenticated bridge state
        # remains authoritative when available.
        host_hint = _host_reachable(host, (80, 443, 3074)) if host else False
        online = bool(bridge_status.get("online")) or host_hint
        state = str(bridge_status.get("state") or ("online" if online else "offline")).lower()
        controller = bridge_status.get("controller") if isinstance(bridge_status.get("controller"), dict) else {}
        snapshot = {
            "platform": self.platform,
            "name": str(bridge_status.get("name") or "Xbox"),
            "online": online,
            "state": state,
            "host": host,
            "active_title": str(bridge_status.get("active_title") or bridge_status.get("title") or ""),
            "activity": str(bridge_status.get("activity") or ""),
            "remote_play_available": self.capabilities()["remote_play"],
            "controller": controller,
            "capabilities": self.capabilities(),
            "bridge_error": bridge_error,
        }
        return _remember(self.platform, snapshot)

    def command(self, action: str, value: str = "") -> str:
        aliases = {"power_on": "wake", "power_off": "shutdown", "playpause": "play_pause"}
        action = aliases.get(action, action)
        if action == "status":
            return format_console_status(self.status())
        if self.bridge.base_url:
            result = self.bridge.command(action, value)
            message = str(result.get("message") or "").strip()
            return message or f"Xbox {action.replace('_', ' ')} command sent through the authenticated bridge."
        if action == "wake" and _env("XBOX_MAC"):
            _magic_packet(_env("XBOX_MAC"))
            return "Xbox network wake packet sent."
        env_map = {
            "wake": "XBOX_WAKE_COMMAND",
            "sleep": "XBOX_SLEEP_COMMAND",
            "shutdown": "XBOX_SHUTDOWN_COMMAND",
            "restart": "XBOX_RESTART_COMMAND",
            "launch": "XBOX_LAUNCH_COMMAND",
            "remote_play": "XBOX_REMOTE_PLAY_COMMAND",
        }
        env_name = env_map.get(action)
        if env_name and _env(env_name):
            _run_configured(_env(env_name), replacements={"title": value})
            return f"Xbox {action.replace('_', ' ')} command sent through the configured local helper."
        if action == "launch":
            raise ConsoleControlError("Xbox game/app launch is unavailable because no authenticated bridge or supported launch helper is configured.")
        raise ConsoleControlError(f"Xbox {action.replace('_', ' ')} is unavailable until XBOX_REMOTE_BRIDGE_URL or a supported local helper is configured.")


PS = PlayStationConsole()
XBOX = XboxConsole()


def _console(platform: str):
    value = platform.strip().lower().replace(" ", "")
    if value in {"ps", "ps5", "playstation", "playstation5"}:
        return PS
    if value in {"xbox", "xboxseries", "xboxseriesx", "xboxseriess"}:
        return XBOX
    raise ConsoleControlError(f"Unknown console platform: {platform}")


def console_status(platform: str = "all") -> dict[str, Any]:
    if platform.strip().lower() in {"", "all", "consoles"}:
        return {"playstation": PS.status(), "xbox": XBOX.status()}
    target = _console(platform)
    return {target.platform: target.status()}


def console_capabilities(platform: str = "all") -> dict[str, Any]:
    if platform.strip().lower() in {"", "all", "consoles"}:
        return {"playstation": PS.capabilities(), "xbox": XBOX.capabilities()}
    target = _console(platform)
    return {target.platform: target.capabilities()}


def console_command(platform: str, action: str, value: str = "", *, confirmed: bool = False) -> str:
    target = _console(platform)
    action = action.strip().lower().replace("-", "_").replace(" ", "_")
    if action in {"shutdown", "restart"} and not confirmed:
        raise ConsoleControlError(f"{action.title()} can interrupt an active game/session. Send the command again with confirmation.")
    return target.command(action, value)


def format_console_status(item: dict[str, Any]) -> str:
    name = str(item.get("name") or item.get("platform") or "Console")
    state = str(item.get("state") or ("online" if item.get("online") else "offline"))
    title = str(item.get("active_title") or "").strip()
    last_seen = item.get("last_seen")
    extra = f" Active title: {title}." if title else ""
    if not item.get("online") and last_seen:
        age = max(0, int(time.time() - float(last_seen)))
        extra += f" Last seen {age}s ago."
    return f"{name} is {state}.{extra}"


_PLATFORM_RE = r"(?:the\s+)?(?P<platform>ps5|playstation(?:\s*5)?|xbox(?:\s+series\s+[xs])?)"


def handle_console_request(text: str) -> str | None:
    raw = " ".join(str(text or "").strip().split())
    lower = raw.lower()
    if not any(word in lower for word in ("ps5", "playstation", "xbox")):
        return None

    platform_match = re.search(_PLATFORM_RE, lower, re.I)
    if not platform_match:
        return None
    platform = platform_match.group("platform")

    try:
        if re.search(r"\b(?:is|what(?:'s| is)|check|show).*(?:on|online|status|state)\b", lower) or re.search(r"\b(?:ps5|playstation|xbox)\s+status\b", lower):
            return format_console_status(next(iter(console_status(platform).values())))
        if re.search(r"\b(?:what(?:'s| is)\s+(?:playing|running)|what am i playing|current (?:game|title|app)|active (?:game|title|app))\b", lower):
            item = next(iter(console_status(platform).values()))
            title = str(item.get("active_title") or "").strip()
            return f"{item.get('name', platform)} is running {title}." if title else f"The configured {platform} integration is not exposing an active title right now."
        if re.search(r"\b(?:wake|turn on|power on)\b", lower):
            return console_command(platform, "wake")
        if re.search(r"\b(?:rest mode|go to sleep|sleep|put .* to rest)\b", lower):
            return console_command(platform, "sleep")
        if re.search(r"\bshutdown|shut down|power off|turn off\b", lower):
            return console_command(platform, "shutdown", confirmed=bool(re.search(r"\bconfirm(?:ed)?\b", lower)))
        if re.search(r"\brestart|reboot\b", lower):
            return console_command(platform, "restart", confirmed=bool(re.search(r"\bconfirm(?:ed)?\b", lower)))
        if re.search(r"\b(?:start|open|launch)\s+(?:remote play|ps remote play|xbox remote play)\b", lower):
            return console_command(platform, "remote_play")
        launch = re.search(r"\b(?:launch|start|open)\s+(.+?)\s+(?:on|using|via)\s+" + _PLATFORM_RE + r"\b", raw, re.I)
        if launch:
            return console_command(platform, "launch", launch.group(1).strip())
        controls = {
            "home": "home", "guide": "home", "back": "back", "menu": "menu",
            "play": "play", "pause": "pause", "play pause": "play_pause",
            "up": "up", "down": "down", "left": "left", "right": "right",
            "select": "select", "ok": "select", "next": "next", "previous": "previous",
        }
        for phrase, action in controls.items():
            if re.search(r"\b" + re.escape(phrase) + r"\b.*\b(?:ps5|playstation|xbox)\b|\b(?:ps5|playstation|xbox)\b.*\b" + re.escape(phrase) + r"\b", lower):
                return console_command(platform, action)
    except (ConsoleControlError, requests.RequestException, OSError, ValueError) as exc:
        return f"Console control failed: {exc}"
    return None
