import json

import pytest

from nekosuneai.windows_gaming_agent import (
    GameProfile, InputSafetyController, TwitchIrcClient, WindowsGamingAgent,
)


def _profile(**changes):
    values = {
        "game_id": "offline-test", "display_name": "Offline Test",
        "window_title_pattern": r"Offline Test", "allow_input": True,
        "skills": {"generic.move": [{"key": "w", "seconds": 0.02}, {"key": "space", "seconds": 0.02}]},
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


def test_agent_advertises_scoped_capabilities_only():
    agent = WindowsGamingAgent(
        {"server_url": "https://neko.local", "device_token": "token"},
        _profile(allow_obs=True, allow_twitch=True),
    )
    caps = agent.capabilities()
    assert "game.skill" in caps
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
