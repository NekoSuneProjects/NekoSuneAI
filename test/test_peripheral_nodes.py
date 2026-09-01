import time

import pytest

from nekosuneai.peripheral_nodes import PeripheralNodeRegistry


def _register(registry):
    pairing = registry.create_pairing("Kitchen Pi")
    return registry.register(
        pairing["pairing_id"],
        pairing["pairing_code"],
        "pi-kitchen",
        "Kitchen Pi",
        "raspberry-pi",
        {
            "sensor.temperature": {"kind": "read"},
            "audio.speak": {"kind": "write"},
        },
        "192.168.1.22",
    )


def test_pairing_token_manifest_and_persistence(tmp_path):
    path = tmp_path / "nodes.json"
    registry = PeripheralNodeRegistry(path)
    registered = _register(registry)
    token = registered["device_token"]

    assert registry.authorize("pi-kitchen", token)
    assert not registry.authorize("pi-kitchen", "wrong")
    assert registered["node"]["capabilities"]["audio.speak"]["policy"] == "confirm"
    assert registry.action_policy("pi-kitchen", "audio.speak") == "confirm"
    assert registry.action_policy("missing", "audio.speak") == "deny"

    restored = PeripheralNodeRegistry(path)
    assert restored.authorize("pi-kitchen", token)
    assert restored.list_nodes()[0]["node_type"] == "raspberry-pi"


def test_pairing_is_one_use_and_capabilities_are_validated(tmp_path):
    registry = PeripheralNodeRegistry(tmp_path / "nodes.json")
    pairing = registry.create_pairing()
    registry.register(pairing["pairing_id"], pairing["pairing_code"], "node-1", "One", "pc", ["server.status"])
    with pytest.raises(PermissionError):
        registry.register(pairing["pairing_id"], pairing["pairing_code"], "node-2", "Two", "pc", ["server.status"])

    other = registry.create_pairing()
    with pytest.raises(ValueError, match="invalid capability"):
        registry.register(other["pairing_id"], other["pairing_code"], "node-2", "Two", "pc", ["shell"])


def test_heartbeat_command_confirmation_and_policy(tmp_path):
    registry = PeripheralNodeRegistry(tmp_path / "nodes.json")
    _register(registry)
    status = registry.heartbeat("pi-kitchen", {"temperature": 22.4}, 13, 47)
    assert status["online"] is True
    assert status["state"]["temperature"] == 22.4

    read = registry.enqueue("pi-kitchen", "sensor.temperature")
    assert read["id"] == 1
    with pytest.raises(PermissionError, match="confirmation"):
        registry.enqueue("pi-kitchen", "audio.speak", {"text": "hello"})

    write = registry.enqueue("pi-kitchen", "audio.speak", {"text": "hello"}, confirmed=True)
    assert [x["id"] for x in registry.wait_commands("pi-kitchen", 1, 0)] == [write["id"]]
    assert registry.heartbeat("pi-kitchen", ack_command_id=write["id"])["pending_commands"] == 0

    registry.set_policy("pi-kitchen", "audio.speak", "deny")
    with pytest.raises(PermissionError, match="denied"):
        registry.enqueue("pi-kitchen", "audio.speak", confirmed=True)


def test_offline_and_revoke(tmp_path):
    registry = PeripheralNodeRegistry(tmp_path / "nodes.json", online_seconds=15)
    registered = _register(registry)
    registry._nodes["pi-kitchen"]["last_seen_epoch"] = time.time() - 16
    assert registry.list_nodes()[0]["online"] is False
    assert registry.revoke("pi-kitchen") is True
    assert not registry.authorize("pi-kitchen", registered["device_token"])
