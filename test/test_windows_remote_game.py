import pytest

from nekosuneai.games.base import GameCommand
from nekosuneai.games.windows_remote import WindowsRemoteGameDriver
from nekosuneai.peripheral_nodes import PeripheralNodeRegistry


def _registry(tmp_path):
    registry = PeripheralNodeRegistry(tmp_path / "nodes.json")
    pairing = registry.create_pairing("Gaming PC")
    registered = registry.register(
        pairing["pairing_id"], pairing["pairing_code"], "gaming-pc", "Gaming PC",
        "windows-gaming", {
            "game.status": {"kind": "read"},
            "game.skill": {"kind": "write"},
            "game.plan": {"kind": "write"},
            "game.input.stop": {"kind": "write"},
        },
    )
    registry.heartbeat("gaming-pc", state={
        "game_id": "offline-test", "game_running": True,
        "active_window": "Offline Test", "input_disabled": False,
        "skills": ["generic.move", "generic.interact"],
        "observation": {"scene_hash": "abcd", "ocr": "Open door", "input_safe": True},
    })
    return registry, registered["device_token"]


def test_autonomous_start_requires_deliberate_allow_policy(tmp_path):
    registry, _token = _registry(tmp_path)
    driver = WindowsRemoteGameDriver(registry)
    with pytest.raises(PermissionError, match="explicitly set game.skill to allow"):
        driver.start()
    registry.set_policy("gaming-pc", "game.skill", "allow")
    driver.start()
    assert driver.is_running() is True
    assert driver.available_verbs() == ["generic.move", "generic.interact"]


def test_observe_and_act_use_only_advertised_named_skills(tmp_path):
    registry, _token = _registry(tmp_path)
    registry.set_policy("gaming-pc", "game.skill", "allow")
    driver = WindowsRemoteGameDriver(registry)
    driver.start()
    observation = driver.observe()
    assert "Open door" in observation.text
    assert "screenshot" not in observation.raw
    result = driver.act(GameCommand("generic.interact"))
    assert result["queued"] is True
    queued = registry.wait_commands("gaming-pc", wait_seconds=0)
    assert queued[-1]["capability"] == "game.skill"
    assert queued[-1]["arguments"] == {"name": "generic.interact"}
    with pytest.raises(ValueError, match="unapproved"):
        driver.act(GameCommand("shell.run"))


def test_transition_blocks_actions_and_stop_queues_emergency_release(tmp_path):
    registry, _token = _registry(tmp_path)
    registry.set_policy("gaming-pc", "game.skill", "allow")
    driver = WindowsRemoteGameDriver(registry)
    driver.start()
    registry.heartbeat("gaming-pc", state={
        "game_id": "offline-test", "game_running": True,
        "active_window": "Offline Test", "input_disabled": False,
        "skills": ["generic.move"],
        "observation": {"scene_hash": "efgh", "transition": "loading", "input_safe": False},
    })
    driver.observe()
    with pytest.raises(PermissionError, match="transitional"):
        driver.act(GameCommand("generic.move"))
    driver.stop()
    assert registry.wait_commands("gaming-pc", wait_seconds=0)[-1]["capability"] == "game.input.stop"


def test_realtime_skill_queues_short_plan_when_owner_allows_it(tmp_path):
    registry, _token = _registry(tmp_path)
    registry.set_policy("gaming-pc", "game.skill", "allow")
    registry.set_policy("gaming-pc", "game.plan", "allow")
    registry.heartbeat("gaming-pc", state={
        "game_id": "offline-test", "game_running": True, "active_window": "Offline Test",
        "input_disabled": False, "skills": ["generic.move"],
        "skill_metadata": {"generic.move": {"realtime": True}},
        "observation": {"scene_hash": "abcd", "input_safe": True},
    })
    driver = WindowsRemoteGameDriver(registry)
    driver.start(); driver.observe()
    result = driver.act(GameCommand("generic.move", {"seconds": 5}))
    assert result["realtime"] is True
    queued = registry.wait_commands("gaming-pc", wait_seconds=0)[-1]
    assert queued["capability"] == "game.plan"
    assert queued["arguments"] == {"name": "generic.move", "seconds": 5.0}
