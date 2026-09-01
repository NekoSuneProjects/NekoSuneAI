import json

import pytest

from nekosuneai.smart_home import SmartHomeManager


def _light(manager, name="Ceiling Light", room="kitchen", unique_id="kitchen_ceiling"):
    return manager.discover(
        f"homeassistant/light/house/{unique_id}/config",
        json.dumps(
            {
                "unique_id": unique_id,
                "name": name,
                "room": room,
                "aliases": ["main light", "lamp"],
                "~": f"house/{unique_id}",
                "command_topic": "~/set",
                "state_topic": "~/state",
                "availability_topic": "~/availability",
                "brightness_command_topic": "~/brightness/set",
                "brightness_scale": 255,
            }
        ),
    )


def test_home_assistant_discovery_aliases_rooms_and_commands(tmp_path):
    published = []
    manager = SmartHomeManager(
        lambda topic, payload, retain=False: published.append((topic, payload, retain)),
        storage_path=tmp_path / "devices.json",
    )
    device = _light(manager)
    assert device["command_topic"] == "house/kitchen_ceiling/set"
    assert set(manager.subscribed_topics()) == {
        "house/kitchen_ceiling/availability",
        "house/kitchen_ceiling/state",
    }

    assert manager.handle("turn the light off", room="kitchen") == "Sent off to Ceiling Light."
    assert published[-1] == ("house/kitchen_ceiling/set", "OFF", False)
    manager.handle("set main light brightness to 20", room="kitchen")
    assert published[-1] == ("house/kitchen_ceiling/brightness/set", "51", False)

    changed = manager.set_aliases("kitchen_ceiling", ["cooking light", "my light"], "galley")
    assert changed["room"] == "galley"
    assert manager.resolve("my light", "galley")["id"] == "kitchen_ceiling"
    assert manager.handle("turn on my light", room="galley") == "Sent on to Ceiling Light."


def test_generic_discovery_state_battery_prediction_and_cost(tmp_path):
    notices = []
    manager = SmartHomeManager(
        lambda *_args: None,
        lambda message, level: notices.append((message, level)),
        tmp_path / "devices.json",
        electricity_price_per_kwh=0.30,
    )
    manager.discover(
        "nekosuneai/devices/desk-plug/config",
        json.dumps(
            {
                "unique_id": "desk-plug",
                "name": "Desk Plug",
                "component": "switch",
                "room": "office",
                "command_topic": "desk/plug/set",
                "state_topic": "desk/plug/state",
            }
        ),
    )
    manager.ingest("desk/plug/state", json.dumps({"battery": 50, "power_w": 20, "energy_kwh": 10}), now=1_000_000)
    manager.ingest("desk/plug/state", json.dumps({"battery": 40, "power_w": 21, "energy_kwh": 10}), now=1_036_000)
    prediction = manager.list_devices()[0]["battery_prediction"]
    assert prediction["percent_per_hour"] == pytest.approx(-1.0)
    assert prediction["hours_to_critical"] == pytest.approx(35.0)
    response = manager.handle("what is desk plug energy?", room="office")
    assert "estimated cost £3.00" in response

    manager.ingest("desk/plug/state", json.dumps({"battery": 10, "power_w": 20}), now=1_144_000)
    assert any("battery is low" in message for message, _ in notices)


def test_unusual_power_detection_and_warning_cooldown(tmp_path):
    notices = []
    manager = SmartHomeManager(
        lambda *_args: None,
        lambda message, level: notices.append((message, level)),
        tmp_path / "devices.json",
    )
    manager.discover(
        "nekosuneai/devices/heater/config",
        json.dumps({
            "unique_id": "heater",
            "name": "Heater",
            "component": "switch",
            "command_topic": "heater/set",
            "state_topic": "heater/state",
        }),
    )
    for index, watts in enumerate([100, 101, 99, 100, 102, 98]):
        manager.ingest("heater/state", json.dumps({"power_w": watts}), now=100_000 + index * 1800)
    manager.ingest("heater/state", json.dumps({"power_w": 400}), now=111_000)
    manager.ingest("heater/state", json.dumps({"power_w": 450}), now=112_000)
    assert len([message for message, _ in notices if "unusual" in message]) == 1


def test_ambiguous_and_read_only_devices_fail_safely(tmp_path):
    manager = SmartHomeManager(lambda *_args: None, storage_path=tmp_path / "devices.json")
    _light(manager, "Kitchen One", "kitchen", "light_one")
    _light(manager, "Kitchen Two", "kitchen", "light_two")
    with pytest.raises(ValueError, match="ambiguous"):
        manager.resolve("light", "kitchen")

    manager.discover(
        "homeassistant/sensor/house/temperature/config",
        json.dumps({"unique_id": "temperature", "name": "Temperature", "state_topic": "house/temp"}),
    )
    with pytest.raises(ValueError, match="read-only"):
        manager.command("temperature", "on")


def test_discovered_devices_persist_without_history_leaking_from_public_view(tmp_path):
    path = tmp_path / "devices.json"
    manager = SmartHomeManager(lambda *_args: None, storage_path=path)
    _light(manager)
    manager.ingest("house/kitchen_ceiling/state", json.dumps({"value": "ON"}), now=1234)
    restored = SmartHomeManager(lambda *_args: None, storage_path=path)
    public = restored.list_devices()[0]
    assert public["state"]["value"] == "ON"
    assert "battery_history" not in public
    assert "power_history" not in public


def test_state_updates_emit_specific_and_generic_sensor_events(tmp_path):
    events = []
    manager = SmartHomeManager(
        lambda *_args: None,
        storage_path=tmp_path / "devices.json",
        event_callback=lambda name, context: events.append((name, context)),
    )
    _light(manager)
    manager.ingest("house/kitchen_ceiling/state", json.dumps({"value": "ON"}), now=1234)
    assert [name for name, _ in events] == [
        "smart_home.kitchen_ceiling.state",
        "smart_home.state",
    ]
    assert events[0][1]["device"]["state"]["value"] == "ON"


def test_empty_discovery_payload_removes_device(tmp_path):
    manager = SmartHomeManager(lambda *_args: None, storage_path=tmp_path / "devices.json")
    _light(manager)
    assert len(manager.list_devices()) == 1
    manager.ingest("homeassistant/light/house/kitchen_ceiling/config", "")
    assert manager.list_devices() == []
