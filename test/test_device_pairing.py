import pytest

from nekosuneai.device_pairing import DevicePairingManager
from nekosuneai.peripheral_nodes import PeripheralNodeRegistry


def test_windows_approval_registers_capabilities_and_persists_type(tmp_path, monkeypatch):
    path = tmp_path / "devices.json"
    monkeypatch.setenv("DEVICE_PAIRING_FILE", str(path))
    pairing = DevicePairingManager()
    request = pairing.request("gaming-pc", "Gaming PC", "192.168.1.10", "windows-gaming")
    assert pairing.pending()[0]["device_type"] == "windows-gaming"
    assert pairing.status(request["request_id"], "gaming-pc")["status"] == "pending"
    pairing.approve(request["request_id"])
    approved = pairing.status(request["request_id"], "gaming-pc")
    registry = PeripheralNodeRegistry(tmp_path / "nodes.json")
    result = registry.register("approved-device", approved["device_token"], "gaming-pc", "Gaming PC", "windows-gaming", {"game.status": {"kind": "read"}})
    assert registry.authorize("gaming-pc", result["device_token"])
    assert "game.status" in result["node"]["capabilities"]
    assert DevicePairingManager().paired()[0]["device_type"] == "windows-gaming"
    assert "device_token" not in pairing.status(request["request_id"], "gaming-pc")


def test_code_pairing_works_when_remote_approval_is_disabled(tmp_path, monkeypatch):
    monkeypatch.setenv("DEVICE_PAIRING_ALLOW_REMOTE", "false")
    pairing = DevicePairingManager(str(tmp_path / "devices.json"))
    with pytest.raises(PermissionError, match="local network"):
        pairing.request("gaming-pc", "Gaming PC", "8.8.8.8", "windows-gaming")
    registry = PeripheralNodeRegistry(tmp_path / "nodes.json")
    code = registry.create_pairing("Gaming PC")
    result = registry.register(code["pairing_id"], code["pairing_code"], "gaming-pc", "Gaming PC", "windows-gaming", {"game.status": {"kind": "read"}}, "8.8.8.8")
    assert registry.authorize("gaming-pc", result["device_token"])
    with pytest.raises(PermissionError, match="invalid or expired"):
        registry.register(code["pairing_id"], code["pairing_code"], "gaming-pc", "Gaming PC", "windows-gaming", {"game.status": {"kind": "read"}})


def test_android_requests_keep_default_device_type(tmp_path):
    pairing = DevicePairingManager(str(tmp_path / "devices.json"))
    assert pairing.request("phone", "Phone", "192.168.1.10")["device_type"] == "android"
