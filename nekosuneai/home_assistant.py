from __future__ import annotations

import json
import threading
import time
from typing import Callable

from .config import Config
from .smart_home import SmartHomeManager
from .home_assistant_api import HomeAssistantApi


class HomeAssistantMqtt:
    """Home Assistant discovery plus generic local MQTT device control."""

    def __init__(
        self,
        config: Config,
        command: Callable[[str], None],
        notify: Callable[[str, str], None] | None = None,
    ) -> None:
        self.config, self.command = config, command
        self.client = None
        self.connected = False
        self.last_connected_epoch = 0.0
        self.last_error = ""
        self._lock = threading.RLock()
        self.devices = SmartHomeManager(self._publish, notify)
        self.api = HomeAssistantApi(
            getattr(config, "home_assistant_url", "") or "",
            getattr(config, "home_assistant_token", "") or "",
            verify_tls=bool(getattr(config, "home_assistant_verify_tls", True)),
            websocket_enabled=bool(getattr(config, "home_assistant_websocket_enabled", True)),
        )

    def start(self) -> None:
        # Direct HA API works independently of MQTT. A Home Assistant OS/
        # Container user can therefore expose all of their existing entities
        # without also configuring a broker.
        self.api.start()
        if self.api.connected:
            self.connected = True

        if not self.config.home_assistant_mqtt_host:
            return
        import paho.mqtt.client as mqtt

        self.client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id="nekosuneai",
            clean_session=True,
        )
        if self.config.home_assistant_mqtt_username:
            self.client.username_pw_set(
                self.config.home_assistant_mqtt_username,
                self.config.home_assistant_mqtt_password,
            )
        self.client.will_set("nekosuneai/status", "offline", retain=True)
        self.client.reconnect_delay_set(min_delay=1, max_delay=60)
        self.client.on_connect = self._connect
        self.client.on_disconnect = self._disconnect
        self.client.on_message = self._message
        try:
            self.client.connect_async(
                self.config.home_assistant_mqtt_host,
                self.config.home_assistant_mqtt_port,
            )
            self.client.loop_start()
        except Exception as exc:
            self.last_error = str(exc)
            self.connected = False

    def stop(self) -> None:
        self.api.stop()
        client = self.client
        if client is None:
            self.connected = False
            return
        try:
            client.publish("nekosuneai/status", "offline", retain=True)
            client.disconnect()
            client.loop_stop()
        except Exception:
            pass
        self.connected = False

    def _connect(self, client, _userdata, _flags, reason_code, _properties) -> None:
        if reason_code != 0:
            self.connected = False
            self.last_error = f"MQTT connect returned {reason_code}"
            return
        self.connected = True
        self.last_connected_epoch = time.time()
        self.last_error = ""
        device = {
            "identifiers": ["nekosuneai"],
            "name": "NekoSuneAI",
            "manufacturer": "NekoSuneProjects",
            "model": "VTuber AI",
        }
        origin = {
            "name": "NekoSuneAI",
            "sw_version": "1.2.1",
            "support_url": "https://github.com/NekoSuneProjects/NekoSuneAI",
        }
        entities = {
            "status": ("sensor", {"name": "Status", "state_topic": "nekosuneai/state/status"}),
            "command": (
                "text",
                {"name": "Command", "command_topic": "nekosuneai/command", "mode": "text", "min": 1, "max": 255},
            ),
            "wake": (
                "button",
                {"name": "Wake and listen", "command_topic": "nekosuneai/wake", "payload_press": "WAKE"},
            ),
        }
        for uid, (component, payload) in entities.items():
            payload.update(
                {
                    "unique_id": f"nekosuneai_{uid}",
                    "device": device,
                    "origin": origin,
                    "availability_topic": "nekosuneai/status",
                }
            )
            client.publish(
                f"homeassistant/{component}/nekosuneai/{uid}/config",
                json.dumps(payload),
                retain=True,
            )
        client.subscribe("nekosuneai/command")
        client.subscribe("nekosuneai/wake")
        client.subscribe("homeassistant/#")
        client.subscribe("nekosuneai/devices/+/config")
        for topic in self.devices.subscribed_topics():
            client.subscribe(topic)
        client.publish("nekosuneai/status", "online", retain=True)

    def _disconnect(self, _client, _userdata, _disconnect_flags, reason_code, _properties) -> None:
        self.connected = False
        if reason_code != 0:
            self.last_error = f"MQTT disconnected ({reason_code}); reconnecting with backoff"

    def _message(self, client, _userdata, msg) -> None:
        text = msg.payload.decode("utf-8", "replace")
        if msg.topic == "nekosuneai/command":
            self.command(text)
            return
        if msg.topic == "nekosuneai/wake":
            self.command(text or "WAKE")
            return
        before = set(self.devices.subscribed_topics())
        self.devices.ingest(msg.topic, text)
        for topic in set(self.devices.subscribed_topics()) - before:
            client.subscribe(topic)

    def _publish(self, topic: str, payload: str, retain: bool = False) -> None:
        with self._lock:
            if not self.client or not self.connected:
                raise RuntimeError("MQTT is not connected; the command was not sent")
            result = self.client.publish(topic, payload, retain=retain)
            rc = getattr(result, "rc", 0)
            if rc != 0:
                raise RuntimeError(f"MQTT publish failed with code {rc}")

    def publish_state(self, state: str) -> None:
        if self.client and self.connected:
            self.client.publish("nekosuneai/state/status", state, retain=True)

    def handle(self, text: str, room: str | None = None) -> str | None:
        # Keep the existing local MQTT resolver first because it knows the
        # Neko node's current room. A syntactically valid smart-home phrase can
        # still refer to an entity that exists only in Home Assistant though,
        # so "not found/unsupported locally" must fall through to the API.
        try:
            local = self.devices.handle(text, room)
        except (ValueError, RuntimeError):
            local = None
        if local is not None:
            return local
        return self.api.handle(text)

    def resolve_device(self, description: str, room: str | None = None) -> dict:
        try:
            return self.devices.resolve(description, room)
        except ValueError:
            return self.api.resolve(description)

    def list_devices(self) -> list[dict]:
        devices = list(self.devices.list_devices())
        devices.extend(self.api.list_entities())
        return devices

    def set_aliases(self, device_id: str, aliases: list[str], room: str | None = None) -> dict:
        return self.devices.set_aliases(device_id, aliases, room)

    def command_device(self, device_id: str, action: str, value=None, confirmed: bool = False) -> str:
        # Home Assistant API entity ids always contain the domain separator.
        if "." in str(device_id) and self.api.configured:
            service_map = {
                "on": "turn_on", "off": "turn_off",
                "open": "open_cover", "close": "close_cover",
                "lock": "lock", "unlock": "unlock",
                "play": "media_play", "pause": "media_pause", "stop": "media_stop",
                "next": "media_next_track", "previous": "media_previous_track",
                "start": "start", "return": "return_to_base",
            }
            entity = self.api.resolve(str(device_id))
            domain = entity["domain"]
            service = service_map.get(str(action).lower(), str(action).lower())
            data = {}
            if service == "set_temperature":
                data["temperature"] = value
            elif service == "set_cover_position":
                data["position"] = int(value)
            elif service == "volume_set":
                data["volume_level"] = max(0.0, min(1.0, float(value)))
            elif service == "select_source":
                data["source"] = str(value)
            elif service == "set_percentage":
                data["percentage"] = int(value)
            return self.api.call_service(str(device_id), service, data, confirmed=confirmed)
        return self.devices.command(device_id, action, value, confirmed=confirmed)

    def status(self) -> dict:
        api_status = self.api.status()
        mqtt_connected = bool(self.connected and self.client is not None)
        connected = mqtt_connected or bool(api_status.get("connected"))
        return {
            "configured": bool(self.config.home_assistant_mqtt_host) or bool(api_status.get("configured")),
            "connected": connected,
            "mqtt": {
                "configured": bool(self.config.home_assistant_mqtt_host),
                "connected": mqtt_connected,
            },
            "api": api_status,
            "last_connected_epoch": max(
                float(self.last_connected_epoch or 0),
                float(api_status.get("last_connected_epoch") or 0),
            ),
            "last_error": self.last_error or str(api_status.get("last_error") or ""),
            "device_count": len(self.list_devices()),
        }
