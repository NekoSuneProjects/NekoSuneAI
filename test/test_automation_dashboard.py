from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_automation_dashboard_has_node_and_routine_controls():
    html = (ROOT / "nekosuneai" / "static" / "automations.html").read_text("utf-8")
    assert "Peripheral Nodes & Routines" in html
    assert "createPairing()" in html
    assert "Routine builder" in html
    assert "Smart-home devices" in html
    assert "get_smart_home_devices" in html
    assert "set_smart_home_aliases" in html
    assert "Stop all input" in html
    assert "streamAction('brb')" in html
    assert "setNodePolicy" in html
    assert "learned skill outcome" in html
    assert "/api/routines/preview" in html
    assert "last_seen_epoch" in html


def test_webserver_exposes_automation_dashboard():
    source = (ROOT / "nekosuneai" / "webserver.py").read_text("utf-8")
    assert 'parsed.path in {"/automations", "/automations/"}' in source
    assert 'relative = "automations.html"' in source
