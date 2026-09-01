import json
import sys
from types import SimpleNamespace

import pytest

from nekosuneai.windows_gaming_agent import (
    GameProfile, InputSafetyController, RealtimeActionLoop, TwitchIrcClient, VirtualGamepad,
    WindowsGamingAgent,
)


def _profile(**changes):
    values = {
        "game_id": "offline-test", "display_name": "Offline Test",
        "window_title_pattern": r"Offline Test", "allow_input": True,
        "skills": {"generic.move": [{"key": "w", "seconds": 0.02}, {"key": "space", "seconds": 0.02}]},
        "skill_metadata": {"generic.move": {"realtime": True}},
    }
    values.update(changes)
    return GameProfile(**values)


def test_profile_loading_disables_input_for_anticheat(tmp_path):
    path = tmp_path / "profile.json"
    path.write_text(json.dumps({
        "game_id": "competitive", "display_name": "Competitive", "window_title_pattern": "Game",
        "competitive_or_anticheat": True, "allow_input": True, "skills": {},
    }), "utf-8")
    profile = GameProfile.load(path)
    assert profile.allow_input is False
    assert profile.competitive_or_anticheat is True


def test_named_skill_only_runs_in_approved_window_and_releases_keys():
    events = []
    controller = InputSafetyController(
        _profile(), foreground=lambda: (1, "Offline Test - level one"),
        key_event=lambda code, down: events.append((code, down)),
    )
    result = controller.run_skill("generic.move")
    assert result == {"ok": True, "skill": "generic.move", "steps": 2}
    assert events == [(0x57, True), (0x57, False), (0x20, True), (0x20, False)]
    assert controller._held == set()

    blocked = InputSafetyController(_profile(), foreground=lambda: (2, "Private desktop"), key_event=lambda *_: None)
    with pytest.raises(PermissionError, match="foreground"):
        blocked.run_skill("generic.move")


def test_emergency_stop_disables_future_input():
    controller = InputSafetyController(_profile(), foreground=lambda: (1, "Offline Test"), key_event=lambda *_: None)
    controller.stop_all(disable=True)
    with pytest.raises(PermissionError, match="locally disabled"):
        controller.run_skill("generic.move")
    controller.enable()
    assert controller.disabled.is_set() is False


def test_mouse_and_controller_steps_are_explicitly_allowlisted():
    events = []

    class Pad:
        def button(self, name, down): events.append(("button", name, down))
        def axis(self, name, value): events.append(("axis", name, value))
        def reset(self): events.append(("reset",))

    profile = _profile(
        allow_mouse=True, allow_controller=True,
        skills={"mixed": [
            {"mouse_move": {"x": 20, "y": -10}, "seconds": 0.02},
            {"mouse_button": "left", "seconds": 0.02},
            {"button": "a", "seconds": 0.02},
            {"axis": "left_x", "value": 0.5, "seconds": 0.02},
        ]},
    )
    controller = InputSafetyController(
        profile, foreground=lambda: (1, "Offline Test"), key_event=lambda *_: None,
        mouse_event=lambda button, down, x, y: events.append(("mouse", button, down, x, y)), gamepad=Pad(),
    )
    assert controller.run_skill("mixed")["steps"] == 4
    assert ("mouse", "move", True, 20, -10) in events
    assert ("button", "a", True) in events
    assert ("axis", "left_x", 0.5) in events


def test_dualshock_dpad_release_uses_neutral_hat_value(monkeypatch):
    events = []

    class Pad:
        def __init__(self): pass
        def directional_pad(self, direction): events.append(direction)
        def update(self): pass
        def reset(self): pass

    fake = SimpleNamespace(
        VDS4Gamepad=Pad, VX360Gamepad=Pad,
        DS4_DPAD_DIRECTIONS=SimpleNamespace(
            DS4_BUTTON_DPAD_NORTH=0, DS4_BUTTON_DPAD_SOUTH=4,
            DS4_BUTTON_DPAD_WEST=6, DS4_BUTTON_DPAD_EAST=2,
            DS4_BUTTON_DPAD_NONE=8,
        ),
        DS4_BUTTONS=SimpleNamespace(), XUSB_BUTTON=SimpleNamespace(),
    )
    monkeypatch.setitem(sys.modules, "vgamepad", fake)
    gamepad = VirtualGamepad("dualshock4")
    gamepad.button("dpad_up", True)
    gamepad.button("dpad_up", False)
    assert events == [0, 8]


def test_multiplayer_profile_fails_closed_until_permission_is_explicit():
    profile = GameProfile.from_mapping({
        "game_id": "server", "display_name": "Server", "window_title_pattern": "Server",
        "allow_input": True, "multiplayer_policy": "private_server", "automation_permitted": False,
        "skills": {"move": [{"key": "w"}]},
    })
    assert profile.allow_input is False


def test_realtime_loop_repeats_short_intent_and_expires():
    calls, outcomes = [], []
    profile = _profile(
        realtime_max_intent_seconds=0.15, realtime_repeat_delay=0.02,
        skills={"walk": [{"key": "w", "seconds": 0.02}]},
        skill_metadata={"walk": {"realtime": True}},
    )
    controller = InputSafetyController(
        profile, foreground=lambda: (1, "Offline Test"),
        key_event=lambda code, down: calls.append((code, down)),
    )
    loop = RealtimeActionLoop(profile, controller, lambda: True, lambda *row: outcomes.append(row))
    loop.start()
    loop.set_intent("walk", 0.12)
    import time
    time.sleep(0.22)
    loop.stop()
    assert len([row for row in calls if row[1]]) >= 2
    assert len(outcomes) >= 2
    assert loop.status()["active"] is False


def test_agent_advertises_scoped_capabilities_only():
    agent = WindowsGamingAgent(
        {"server_url": "https://neko.local", "device_token": "token"},
        _profile(allow_obs=True, allow_twitch=True),
    )
    caps = agent.capabilities()
    assert "game.skill" in caps
    assert "game.plan" in caps
    assert "game.input.stop" in caps
    assert "obs.stream.start" in caps
    assert "twitch.chat.send" in caps
    assert not any("shell" in name or "desktop" in name for name in caps)
    assert caps["obs.stream.start"]["kind"] == "write"


def test_twitch_irc_parser_keeps_only_public_message_fields():
    row = TwitchIrcClient.parse_line(
        "@id=abc;display-name=Viewer;msg-id=highlighted-message :viewer!viewer@viewer.tmi.twitch.tv PRIVMSG #channel :Hi NekoSuneAI?"
    )
    assert row["id"] == "abc"
    assert row["user"] == "Viewer"
    assert row["text"] == "Hi NekoSuneAI?"
    assert row["highlighted"] is True
