from __future__ import annotations

"""Direct Home Assistant REST/WebSocket integration.

This is intentionally generic: Home Assistant remains the integration hub and
NekoSuneAI talks to entities/services exposed by that Home Assistant instance.
That means Xbox, PlayStation/TV bridges, Cast, DLNA, vacuums, lights, covers,
climate devices and future integrations do not each need a Neko-specific
driver.

Only entity-scoped, allowlisted service calls are exposed to natural-language
chat. There is no arbitrary service-call or template endpoint in the assistant
surface.
"""

import json
import re
import ssl
import threading
import time
from typing import Any
from urllib.parse import urlparse, urlunparse

import requests

try:
    import websocket
except Exception:  # optional at import time; requirements.txt installs it
    websocket = None  # type: ignore[assignment]


SAFE_DOMAINS = {
    "light", "switch", "input_boolean", "fan", "cover", "lock", "climate",
    "media_player", "remote", "vacuum", "scene", "script", "button",
    "automation", "sensor", "binary_sensor", "camera", "device_tracker",
    "person",
}
READ_ONLY_DOMAINS = {"sensor", "binary_sensor", "camera", "device_tracker", "person"}
SENSITIVE = {("lock", "unlock"), ("cover", "open_cover")}

# Services Neko is allowed to invoke per domain. Keeping this explicit is what
# prevents a compromised prompt from turning the HA API token into arbitrary
# Home Assistant administration access.
ALLOWED_SERVICES: dict[str, set[str]] = {
    "light": {"turn_on", "turn_off"},
    "switch": {"turn_on", "turn_off"},
    "input_boolean": {"turn_on", "turn_off"},
    "fan": {"turn_on", "turn_off", "set_percentage"},
    "cover": {"open_cover", "close_cover", "stop_cover", "set_cover_position"},
    "lock": {"lock", "unlock"},
    "climate": {"turn_on", "turn_off", "set_temperature", "set_hvac_mode"},
    "media_player": {
        "turn_on", "turn_off", "media_play", "media_pause", "media_stop",
        "media_next_track", "media_previous_track", "volume_set", "volume_up",
        "volume_down", "volume_mute", "select_source", "play_media",
    },
    "remote": {"turn_on", "turn_off", "send_command"},
    "vacuum": {"start", "stop", "pause", "return_to_base"},
    "scene": {"turn_on"},
    "script": {"turn_on"},
    "button": {"press"},
    "automation": {"turn_on", "turn_off", "trigger"},
}


def _norm(value: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", str(value).lower()).split())


class HomeAssistantApi:
    def __init__(
        self,
        base_url: str = "",
        token: str = "",
        *,
        verify_tls: bool = True,
        websocket_enabled: bool = True,
        timeout: float = 8.0,
    ) -> None:
        self.base_url = str(base_url or "").strip().rstrip("/")
        self.token = str(token or "").strip()
        self.verify_tls = bool(verify_tls)
        self.websocket_enabled = bool(websocket_enabled)
        self.timeout = max(2.0, float(timeout))
        self.session = requests.Session()
        self.connected = False
        self.websocket_connected = False
        self.last_error = ""
        self.last_connected_epoch = 0.0
        self._entities: dict[str, dict[str, Any]] = {}
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_sync = 0.0

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.token)

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def start(self) -> None:
        if not self.configured:
            return
        try:
            self.refresh(force=True)
        except Exception as exc:
            self.last_error = str(exc)[:500]
        if self.websocket_enabled and websocket is not None:
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._ws_loop, daemon=True, name="home-assistant-ws"
            )
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self.websocket_connected = False

    def _request(self, method: str, path: str, **kwargs: Any) -> requests.Response:
        if not self.configured:
            raise RuntimeError("Home Assistant API URL/token are not configured")
        response = self.session.request(
            method,
            self.base_url + path,
            headers=self._headers(),
            timeout=self.timeout,
            verify=self.verify_tls,
            **kwargs,
        )
        if response.status_code in {401, 403}:
            raise RuntimeError("Home Assistant rejected the access token")
        response.raise_for_status()
        self.connected = True
        self.last_connected_epoch = time.time()
        self.last_error = ""
        return response

    def refresh(self, *, force: bool = False) -> list[dict[str, Any]]:
        if not self.configured:
            return []
        if not force and time.time() - self._last_sync < 5.0:
            return self.list_entities(refresh=False)
        try:
            payload = self._request("GET", "/api/states").json()
            if not isinstance(payload, list):
                raise RuntimeError("Home Assistant /api/states returned an unexpected response")
            with self._lock:
                self._entities = {
                    str(item.get("entity_id")): item
                    for item in payload
                    if isinstance(item, dict)
                    and "." in str(item.get("entity_id") or "")
                    and str(item.get("entity_id")).split(".", 1)[0] in SAFE_DOMAINS
                }
                self._last_sync = time.time()
            return self.list_entities(refresh=False)
        except Exception as exc:
            self.connected = False
            self.last_error = str(exc)[:500]
            raise

    @staticmethod
    def public_entity(item: dict[str, Any]) -> dict[str, Any]:
        entity_id = str(item.get("entity_id") or "")
        domain = entity_id.split(".", 1)[0] if "." in entity_id else ""
        attrs = dict(item.get("attributes") or {})
        # HA attributes are device state, not secrets, but trim huge blobs.
        clean_attrs = {
            str(k): v for k, v in attrs.items()
            if k not in {"entity_picture", "access_token"}
            and len(str(v)) < 4000
        }
        return {
            "id": entity_id,
            "entity_id": entity_id,
            "domain": domain,
            "name": str(attrs.get("friendly_name") or entity_id.split(".", 1)[-1].replace("_", " ")),
            "state": item.get("state"),
            "attributes": clean_attrs,
            "room": str(attrs.get("area_name") or attrs.get("room") or ""),
            "source": "home-assistant-api",
            "available": str(item.get("state")) not in {"unavailable", "unknown"},
            "last_changed": item.get("last_changed"),
            "last_updated": item.get("last_updated"),
        }

    def list_entities(self, *, refresh: bool = True) -> list[dict[str, Any]]:
        if refresh and self.configured:
            try:
                self.refresh()
            except Exception:
                pass
        with self._lock:
            return [self.public_entity(x) for x in self._entities.values()]

    def resolve(self, description: str, domain: str | None = None) -> dict[str, Any]:
        wanted = _norm(description)
        if not wanted:
            raise ValueError("device name is empty")
        entities = self.list_entities()
        scored: list[tuple[int, dict[str, Any]]] = []
        for item in entities:
            if domain and item["domain"] != domain:
                continue
            names = {
                _norm(item["name"]),
                _norm(item["entity_id"]),
                _norm(item["entity_id"].split(".", 1)[-1]),
            }
            aliases = item.get("attributes", {}).get("aliases")
            if isinstance(aliases, list):
                names.update(_norm(x) for x in aliases)
            score = 0
            if wanted in names:
                score = 100
            elif any(wanted in name or name in wanted for name in names if name):
                score = 70
            if score:
                scored.append((score, item))
        if not scored:
            raise ValueError(f"I couldn't find a Home Assistant entity matching {description}.")
        scored.sort(key=lambda x: x[0], reverse=True)
        best = [x for x in scored if x[0] == scored[0][0]]
        if len(best) != 1:
            names = ", ".join(str(x[1]["name"]) for x in best[:6])
            raise ValueError(f"That Home Assistant entity name is ambiguous: {names}.")
        return best[0][1]

    @staticmethod
    def _canonical_source(entity: dict[str, Any], requested: str) -> str:
        wanted = str(requested or "").strip()
        source_list = (entity.get("attributes") or {}).get("source_list")
        if isinstance(source_list, list):
            for item in source_list:
                if str(item).casefold() == wanted.casefold():
                    return str(item)
        return wanted

    def call_service(
        self,
        entity_id: str,
        service: str,
        data: dict[str, Any] | None = None,
        *,
        confirmed: bool = False,
    ) -> str:
        entity_id = str(entity_id).strip()
        if "." not in entity_id:
            raise ValueError("invalid Home Assistant entity id")
        domain = entity_id.split(".", 1)[0]
        service = str(service).strip()
        if domain not in ALLOWED_SERVICES or service not in ALLOWED_SERVICES[domain]:
            raise PermissionError(f"{domain}.{service} is not an allowed NekoSuneAI Home Assistant action")
        if (domain, service) in SENSITIVE and not confirmed:
            raise PermissionError(f"{domain}.{service} requires explicit confirmation")
        body = {"entity_id": entity_id, **dict(data or {})}
        self._request("POST", f"/api/services/{domain}/{service}", json=body)
        # Refresh asynchronously through WS where available; otherwise the next
        # list/status request does a bounded REST refresh.
        return f"Sent {service.replace('_', ' ')} to {entity_id} through Home Assistant."

    def status(self) -> dict[str, Any]:
        return {
            "configured": self.configured,
            "connected": self.connected,
            "websocket_connected": self.websocket_connected,
            "last_connected_epoch": self.last_connected_epoch,
            "last_error": self.last_error,
            "entity_count": len(self._entities),
            "url": self.base_url if self.configured else "",
        }

    def handle(self, text: str) -> str | None:
        if not self.configured:
            return None
        cleaned = " ".join(str(text or "").strip().lower().split())
        if not cleaned:
            return None

        # Questions first.
        match = re.match(r"^(?:what(?:'s| is)|show|check) (?:the )?(.+?) (?:status|state)[?]?$", cleaned)
        if match:
            entity = self.resolve(match.group(1))
            return f"{entity['name']} is {entity['state']}."

        match = re.match(r"^(?:what(?:'s| is)|show|check) (?:the )?(.+?) (?:playing|running)[?]?$", cleaned)
        if match:
            entity = self.resolve(match.group(1))
            attrs = entity.get("attributes") or {}
            title = attrs.get("media_title") or attrs.get("app_name") or attrs.get("source")
            return f"{entity['name']} is {entity['state']}" + (f" — {title}." if title else ".")

        # Power and common binary entities.
        match = re.match(r"^(?:turn|switch|power) (on|off) (?:the )?(.+)$", cleaned)
        if not match:
            match = re.match(r"^(?:turn|switch|power) (?:the )?(.+?) (on|off)$", cleaned)
            if match:
                target, mode = match.group(1), match.group(2)
            else:
                target = mode = ""
        else:
            mode, target = match.group(1), match.group(2)
        if target:
            entity = self.resolve(target)
            if entity["domain"] in {"light", "switch", "input_boolean", "fan", "climate", "media_player", "remote", "automation"}:
                return self.call_service(entity["entity_id"], "turn_on" if mode == "on" else "turn_off")

        brightness = re.match(r"^(?:set|dim) (?:the )?(.+?)(?: brightness)? (?:to )?(\d{1,3})%?$", cleaned)
        if brightness:
            entity = self.resolve(brightness.group(1), "light")
            return self.call_service(
                entity["entity_id"], "turn_on",
                {"brightness_pct": max(0, min(100, int(brightness.group(2))))},
            )

        colour = re.match(r"^(?:set|make|change) (?:the )?(.+?)(?: colour| color)? (?:to )?(red|green|blue|white|warm white|cool white|yellow|orange|purple|pink|cyan)$", cleaned)
        if colour:
            rgb = {
                "red": [255, 0, 0], "green": [0, 255, 0], "blue": [0, 0, 255],
                "white": [255, 255, 255], "warm white": [255, 214, 170],
                "cool white": [201, 226, 255], "yellow": [255, 255, 0],
                "orange": [255, 128, 0], "purple": [128, 0, 255],
                "pink": [255, 64, 160], "cyan": [0, 255, 255],
            }[colour.group(2)]
            entity = self.resolve(colour.group(1), "light")
            return self.call_service(entity["entity_id"], "turn_on", {"rgb_color": rgb})

        colour_temp = re.match(r"^(?:set|change) (?:the )?(.+?)(?: colour temperature| color temperature) (?:to )?(\d{4,5})\s*(?:k|kelvin)?$", cleaned)
        if colour_temp:
            entity = self.resolve(colour_temp.group(1), "light")
            return self.call_service(
                entity["entity_id"], "turn_on",
                {"color_temp_kelvin": max(1000, min(10000, int(colour_temp.group(2))))},
            )

        fan = re.match(r"^(?:set )?(?:the )?(.+?) fan (?:speed |percentage )?(?:to )?(\d{1,3})%$", cleaned)
        if fan:
            try:
                entity = self.resolve(fan.group(1) + " fan", "fan")
            except ValueError:
                entity = self.resolve(fan.group(1), "fan")
            return self.call_service(
                entity["entity_id"], "set_percentage",
                {"percentage": max(0, min(100, int(fan.group(2))))},
            )

        # Media controls work for Xbox, TVs, Cast, DLNA, receivers, etc. as long
        # as Home Assistant exposes them as media_player entities.
        media = re.match(r"^(play|pause|stop|next|previous) (?:on )?(?:the )?(.+)$", cleaned)
        if media:
            entity = self.resolve(media.group(2), "media_player")
            service = {
                "play": "media_play", "pause": "media_pause", "stop": "media_stop",
                "next": "media_next_track", "previous": "media_previous_track",
            }[media.group(1)]
            return self.call_service(entity["entity_id"], service)

        volume = re.match(r"^(?:set )?(?:the )?(.+?) volume (?:to )?(\d{1,3})%?$", cleaned)
        if volume:
            entity = self.resolve(volume.group(1), "media_player")
            level = max(0, min(100, int(volume.group(2)))) / 100.0
            return self.call_service(entity["entity_id"], "volume_set", {"volume_level": level})

        source = re.match(r"^(?:set|switch) (?:the )?(.+?) (?:source|input) (?:to )?(.+)$", cleaned)
        if source:
            entity = self.resolve(source.group(1), "media_player")
            return self.call_service(
                entity["entity_id"], "select_source",
                {"source": self._canonical_source(entity, source.group(2).strip())},
            )

        launch = re.match(r"^(?:launch|open|start) (.+?) (?:on|using) (?:the )?(.+)$", cleaned)
        if launch:
            entity = self.resolve(launch.group(2), "media_player")
            return self.call_service(
                entity["entity_id"], "select_source",
                {"source": self._canonical_source(entity, launch.group(1).strip())},
            )

        remote = re.match(r"^(?:press|send) (.+?) (?:on|to) (?:the )?(.+?)(?: remote)?$", cleaned)
        if remote:
            entity = self.resolve(remote.group(2), "remote")
            command = remote.group(1).strip()
            return self.call_service(entity["entity_id"], "send_command", {"command": command})

        # Covers, locks and climate.
        cover = re.match(r"^(open|close) (?:the )?(.+)$", cleaned)
        if cover:
            entity = self.resolve(cover.group(2))
            if entity["domain"] == "cover":
                return self.call_service(entity["entity_id"], "open_cover" if cover.group(1) == "open" else "close_cover")

        position = re.match(r"^(?:set|move) (?:the )?(.+?)(?: position)? (?:to )?(\d{1,3})%$", cleaned)
        if position:
            entity = self.resolve(position.group(1), "cover")
            return self.call_service(entity["entity_id"], "set_cover_position", {"position": max(0, min(100, int(position.group(2))))})

        lock = re.match(r"^(confirm )?(lock|unlock) (?:the )?(.+)$", cleaned)
        if lock:
            entity = self.resolve(lock.group(3), "lock")
            return self.call_service(entity["entity_id"], lock.group(2), confirmed=bool(lock.group(1)))

        temp = re.match(r"^(?:set|change) (?:the )?(.+?) (?:temperature )?(?:to )?(\d{1,2}(?:\.\d+)?)\s*(?:degrees|degree|°c|c)?$", cleaned)
        if temp:
            entity = self.resolve(temp.group(1), "climate")
            return self.call_service(entity["entity_id"], "set_temperature", {"temperature": float(temp.group(2))})

        # Vacuums / scenes / scripts / buttons.
        vac = re.match(r"^(start|stop|pause|dock|return) (?:the )?(.+?)(?: vacuum)?$", cleaned)
        if vac:
            entity = self.resolve(vac.group(2), "vacuum")
            service = {"start": "start", "stop": "stop", "pause": "pause", "dock": "return_to_base", "return": "return_to_base"}[vac.group(1)]
            return self.call_service(entity["entity_id"], service)

        scene = re.match(r"^(?:run|activate) (?:the )?(.+?)(?: scene)?$", cleaned)
        if scene:
            try:
                entity = self.resolve(scene.group(1), "scene")
            except ValueError:
                try:
                    entity = self.resolve(scene.group(1), "script")
                except ValueError:
                    return None
            return self.call_service(entity["entity_id"], "turn_on")

        button = re.match(r"^press (?:the )?(.+)$", cleaned)
        if button:
            entity = self.resolve(button.group(1), "button")
            return self.call_service(entity["entity_id"], "press")

        return None

    def _ws_url(self) -> str:
        parsed = urlparse(self.base_url)
        scheme = "wss" if parsed.scheme == "https" else "ws"
        path = parsed.path.rstrip("/") + "/api/websocket"
        return urlunparse((scheme, parsed.netloc, path, "", "", ""))

    def _ws_loop(self) -> None:
        if websocket is None:
            return
        while not self._stop.is_set():
            ws = None
            try:
                sslopt = {"cert_reqs": ssl.CERT_REQUIRED if self.verify_tls else ssl.CERT_NONE}
                ws = websocket.create_connection(self._ws_url(), timeout=15, sslopt=sslopt)
                hello = json.loads(ws.recv())
                if hello.get("type") != "auth_required":
                    raise RuntimeError("unexpected Home Assistant WebSocket greeting")
                ws.send(json.dumps({"type": "auth", "access_token": self.token}))
                auth = json.loads(ws.recv())
                if auth.get("type") != "auth_ok":
                    raise RuntimeError("Home Assistant WebSocket authentication failed")
                ws.send(json.dumps({"id": 1, "type": "subscribe_events", "event_type": "state_changed"}))
                self.websocket_connected = True
                self.connected = True
                self.last_connected_epoch = time.time()
                self.last_error = ""
                while not self._stop.is_set():
                    message = json.loads(ws.recv())
                    if message.get("type") != "event":
                        continue
                    event = ((message.get("event") or {}).get("data") or {})
                    new_state = event.get("new_state")
                    entity_id = str(event.get("entity_id") or "")
                    if not entity_id or "." not in entity_id:
                        continue
                    domain = entity_id.split(".", 1)[0]
                    with self._lock:
                        if new_state is None:
                            self._entities.pop(entity_id, None)
                        elif domain in SAFE_DOMAINS and isinstance(new_state, dict):
                            self._entities[entity_id] = new_state
            except Exception as exc:
                self.websocket_connected = False
                self.last_error = str(exc)[:500]
                if self._stop.wait(5.0):
                    break
            finally:
                if ws is not None:
                    try:
                        ws.close()
                    except Exception:
                        pass
                self.websocket_connected = False
