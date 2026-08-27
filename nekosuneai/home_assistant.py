from __future__ import annotations

import json
from typing import Callable

from .config import Config


class HomeAssistantMqtt:
    def __init__(self, config: Config, command: Callable[[str], None]) -> None:
        self.config, self.command = config, command
        self.client = None

    def start(self) -> None:
        if not self.config.home_assistant_mqtt_host: return
        import paho.mqtt.client as mqtt
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="nekosuneai", clean_session=True)
        if self.config.home_assistant_mqtt_username:
            self.client.username_pw_set(self.config.home_assistant_mqtt_username, self.config.home_assistant_mqtt_password)
        self.client.will_set("nekosuneai/status", "offline", retain=True)
        self.client.on_connect = self._connect
        self.client.on_message = lambda _c, _u, msg: self.command(msg.payload.decode("utf-8", "replace"))
        self.client.connect_async(self.config.home_assistant_mqtt_host, self.config.home_assistant_mqtt_port)
        self.client.loop_start()

    def _connect(self, client, _userdata, _flags, reason_code, _properties) -> None:
        if reason_code != 0: return
        device = {"identifiers":["nekosuneai"], "name":"NekoSuneAI", "manufacturer":"NekoSuneProjects", "model":"VTuber AI"}
        origin = {"name":"NekoSuneAI", "sw_version":"1.2.1", "support_url":"https://github.com/NekoSuneProjects/NekoSuneAI"}
        entities = {
            "status": ("sensor", {"name":"Status", "state_topic":"nekosuneai/state/status"}),
            "command": ("text", {"name":"Command", "command_topic":"nekosuneai/command", "mode":"text", "min":1, "max":255}),
            "wake": ("button", {"name":"Wake and listen", "command_topic":"nekosuneai/wake", "payload_press":"WAKE"}),
        }
        for uid, (component, payload) in entities.items():
            payload.update({"unique_id":f"nekosuneai_{uid}", "device":device, "origin":origin, "availability_topic":"nekosuneai/status"})
            client.publish(f"homeassistant/{component}/nekosuneai/{uid}/config", json.dumps(payload), retain=True)
        client.subscribe("nekosuneai/command"); client.subscribe("nekosuneai/wake")
        client.publish("nekosuneai/status", "online", retain=True)

    def publish_state(self, state: str) -> None:
        if self.client: self.client.publish("nekosuneai/state/status", state, retain=True)
