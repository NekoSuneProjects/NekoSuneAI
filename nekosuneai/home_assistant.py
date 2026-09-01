from __future__ import annotations

import json
import threading
import time
from typing import Callable

from .config import Config
from .smart_home import SmartHomeManager


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

    def start(self) -> None:
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
        client = self.client
        if client is None:
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
        return self.devices.handle(text, room)

    def list_devices(self) -> list[dict]:
        return self.devices.list_devices()

    def set_aliases(self, device_id: str, aliases: list[str], room: str | None = None) -> dict:
        return self.devices.set_aliases(device_id, aliases, room)

    def command_device(self, device_id: str, action: str, value=None, confirmed: bool = False) -> str:
        return self.devices.command(device_id, action, value, confirmed=confirmed)

    def status(self) -> dict:
        return {
            "configured": bool(self.config.home_assistant_mqtt_host),
            "connected": self.connected,
            "last_connected_epoch": self.last_connected_epoch,
            "last_error": self.last_error,
            "device_count": len(self.devices.list_devices()),
        }
