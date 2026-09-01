import time

import pytest

from nekosuneai.home_events import HomeEventTimeline
from nekosuneai.stream_sessions import StreamSessionManager


def _node(**state_changes):
    state = {
        "game_id": "minecraft", "game_running": True, "active_window": "Minecraft",
        "input_disabled": False, "observation": {"ok": True},
        "obs": {"connected": True, "streaming": False},
    }
    state.update(state_changes)
    return {
        "node_id": "windows-pc", "name": "Windows Gaming Node", "node_type": "windows-gaming",
        "online": True, "state": state, "capabilities": {"game.input.stop": {}},
    }


def test_preflight_reports_each_blocker(tmp_path):
    manager = StreamSessionManager(lambda: [_node()], lambda *args, **kwargs: {}, HomeEventTimeline(tmp_path / "events.json"))
    assert manager.preflight("minecraft")["ready"] is True
    blocked = StreamSessionManager(
        lambda: [_node(game_running=False, obs={"connected": False, "streaming": False})],
        lambda *args, **kwargs: {}, HomeEventTimeline(tmp_path / "blocked.json"),
    ).preflight("minecraft")
    assert blocked["ready"] is False
    assert "game running" in blocked["blockers"]
    assert "obs connected" in blocked["blockers"]


def test_stream_start_requires_confirmation_and_stop_input_is_queued(tmp_path):
    calls = []
    manager = StreamSessionManager(
        lambda: [_node()],
        lambda node, capability, arguments, **kwargs: calls.append((node, capability, arguments, kwargs)) or {"id": 7},
        HomeEventTimeline(tmp_path / "events.json"),
    )
    assert manager.action("start_stream")["status"] == "confirmation_required"
    assert calls == []
    assert manager.action("start_stream", confirmed=True)["status"] == "queued"
    assert calls[-1][1] == "obs.stream.start"
    assert calls[-1][3]["confirmed"] is True
    manager.action("stop_input", confirmed=True)
    assert calls[-1][1] == "game.input.stop"


def test_offline_or_ambiguous_windows_nodes_fail_closed(tmp_path):
    manager = StreamSessionManager(lambda: [], lambda *args, **kwargs: {}, HomeEventTimeline(tmp_path / "events.json"))
    assert manager.preflight()["ready"] is False
    with pytest.raises(ValueError, match="no Windows Gaming Node"):
        manager.status()
