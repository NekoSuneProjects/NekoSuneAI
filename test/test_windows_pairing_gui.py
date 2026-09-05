from types import SimpleNamespace
from unittest.mock import Mock
from pathlib import Path
import runpy

import pytest
import requests

from tools import windows_gaming_node_gui as gui
from nekosuneai.windows_gaming_agent import WindowsGamingAgent


def response(status, payload):
    result = requests.Response()
    result.status_code = status
    result.json = lambda: payload
    return result


def app_state():
    callbacks = []
    app = SimpleNamespace(
        pairing_busy=False, save=lambda: True, _profile=lambda: object(),
        config_data={"server_url": "https://example.test", "node_id": "test-pc"},
        pairing_id_var=Mock(get=lambda: "pair-id"),
        pairing_code_var=Mock(get=lambda: "ABC123"),
        pair_button=Mock(), code_pair_button=Mock(), connection_var=Mock(),
        pairing_status_var=Mock(), status_var=Mock(),
        after=lambda delay, callback: callbacks.append(callback),
        _pair_failed=Mock(), _pair_success=Mock(), _pair_waiting=Mock(),
    )
    return app, callbacks


@pytest.mark.parametrize("use_code", [False, True])
def test_pairing_success_saves_node_token(monkeypatch, use_code):
    app, callbacks = app_state()
    session = Mock()
    session.post.return_value = response(200, {"request_id": "request-id"})
    session.get.return_value = response(200, {"status": "approved", "device_token": "approval-token"})
    monkeypatch.setattr(gui.requests, "Session", lambda: session)
    agent = Mock()
    agent.pair.return_value = "node-token"
    monkeypatch.setattr(gui, "WindowsGamingAgent", lambda *args: agent)
    saved = Mock()
    monkeypatch.setattr(gui, "save_config", saved)
    monkeypatch.setattr(gui.time, "sleep", lambda _: None)
    monkeypatch.setattr(gui.threading, "Thread", lambda target, **kw: SimpleNamespace(start=target))
    gui.App.pair(app, use_code=use_code)
    for callback in callbacks:
        callback()
    agent.pair.assert_called_once_with(*(("pair-id", "ABC123") if use_code else ("approved-device", "approval-token")))
    assert saved.call_args.args[0]["device_token"] == "node-token"
    app._pair_success.assert_called_once_with(saved.call_args.args[0])
    app._pair_failed.assert_not_called()
    if use_code:
        session.post.assert_not_called()
    else:
        assert session.post.call_args.kwargs["json"]["device_type"] == "windows-gaming"


def test_pairing_failure_survives_deferred_tk_callback(monkeypatch):
    app, callbacks = app_state()
    session = Mock()
    session.post.return_value = response(403, {"error": "pairing requests are limited to the local network"})
    monkeypatch.setattr(gui.requests, "Session", lambda: session)
    monkeypatch.setattr(gui.threading, "Thread", lambda target, **kw: SimpleNamespace(start=target))
    gui.App.pair(app)
    # Tk executes this after the worker's exception variable has been cleared.
    for callback in callbacks:
        callback()
    error = app._pair_failed.call_args.args[0]
    assert "local network" in error
    assert "Pair with code" in error


def test_registration_shows_server_error_and_rejects_missing_token():
    agent = object.__new__(WindowsGamingAgent)
    agent.session = Mock()
    agent.server = "https://example.test"
    agent.config = {}
    agent.node_id = "test-pc"
    agent.verify_tls = True
    agent.capabilities = lambda: {}
    agent.session.post.return_value = response(403, {"error": "invalid or expired pairing code"})
    with pytest.raises(RuntimeError, match="invalid or expired pairing code"):
        agent.pair("id", "code")
    agent.session.post.return_value = response(200, {})
    with pytest.raises(RuntimeError, match="no device token"):
        agent.pair("id", "code")


def test_pairing_controls_are_reachable_at_minimum_window_size():
    app = gui.App()
    app.attributes("-alpha", 0)
    try:
        for size in ("920x620", "1080x720"):
            app.geometry(size)
            app.update()
            app.page_canvas.yview_moveto(1)
            app.update()
            button = app.code_pair_button
            canvas = app.page_canvas
            assert button.winfo_width() >= button.winfo_reqwidth()
            assert button.winfo_rootx() >= canvas.winfo_rootx()
            assert button.winfo_rootx() + button.winfo_width() <= canvas.winfo_rootx() + canvas.winfo_width()
            assert button.winfo_rooty() >= canvas.winfo_rooty()
            assert button.winfo_rooty() + button.winfo_height() <= canvas.winfo_rooty() + canvas.winfo_height()
    finally:
        app.destroy()


def test_standalone_exe_uses_bundled_game_profiles(tmp_path, monkeypatch):
    bundle = Path(gui.__file__).resolve().parents[1]
    monkeypatch.setattr(gui.sys, "frozen", True, raising=False)
    monkeypatch.setattr(gui.sys, "executable", str(tmp_path / "GamingNode.exe"))
    monkeypatch.setattr(gui.sys, "_MEIPASS", str(bundle), raising=False)
    module = runpy.run_path(gui.__file__)
    assert module["BASE_DIR"] == tmp_path
    profiles = gui.GameSkillLibrary(module["SKILLS_ROOT"]).discover()
    assert profiles
