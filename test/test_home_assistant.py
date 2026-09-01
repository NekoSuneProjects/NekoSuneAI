import json
from types import SimpleNamespace

import pytest

from nekosuneai.home_assistant import HomeAssistantMqtt


class PublishResult:
    rc = 0


class FakeClient:
    def __init__(self):
        self.published = []
        self.subscribed = []

    def publish(self, topic, payload, retain=False):
        self.published.append((topic, payload, retain))
        return PublishResult()

    def subscribe(self, topic):
        self.subscribed.append(topic)


def _config():
    return SimpleNamespace(
        home_assistant_mqtt_host="mqtt.local",
        home_assistant_mqtt_port=1883,
        home_assistant_mqtt_username=None,
        home_assistant_mqtt_password=None,
    )


def test_connect_discovers_neko_and_subscribes_for_devices(tmp_path, monkeypatch):
    monkeypatch.setenv("SMART_HOME_DEVICES_FILE", str(tmp_path / "devices.json"))
    integration = HomeAssistantMqtt(_config(), lambda _text: None)
    client = FakeClient()
    integration.client = client
    integration._connect(client, None, None, 0, None)

    assert integration.connected is True
    assert "homeassistant/#" in client.subscribed
    assert "nekosuneai/devices/+/config" in client.subscribed
    assert any(topic.endswith("/status/config") for topic, _, _ in client.published)
    assert ("nekosuneai/status", "online", True) in client.published


def test_discovery_message_subscribes_state_and_routes_command(tmp_path, monkeypatch):
    monkeypatch.setenv("SMART_HOME_DEVICES_FILE", str(tmp_path / "devices.json"))
    commands = []
    integration = HomeAssistantMqtt(_config(), commands.append)
    client = FakeClient()
    integration.client = client
    integration.connected = True
    payload = json.dumps({
        "unique_id": "hall-light",
        "name": "Hall Light",
        "room": "hall",
        "command_topic": "hall/light/set",
        "state_topic": "hall/light/state",
    }).encode()
    integration._message(client, None, SimpleNamespace(topic="homeassistant/light/home/hall/config", payload=payload))
    assert "hall/light/state" in client.subscribed

    integration._message(client, None, SimpleNamespace(topic="nekosuneai/command", payload=b"hello"))
    assert commands == ["hello"]
    assert integration.handle("turn the light on", "hall") == "Sent on to Hall Light."
    assert ("hall/light/set", "ON", False) in client.published


def test_disconnected_publish_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setenv("SMART_HOME_DEVICES_FILE", str(tmp_path / "devices.json"))
    integration = HomeAssistantMqtt(_config(), lambda _text: None)
    with pytest.raises(RuntimeError, match="not connected"):
        integration._publish("device/set", "ON")
    integration._disconnect(None, None, None, 7, None)
    assert "reconnecting with backoff" in integration.last_error
