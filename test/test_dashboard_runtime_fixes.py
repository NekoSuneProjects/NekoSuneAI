from pathlib import Path


def test_dashboard_runtime_patch_contains_pairing_modal_and_vrm_upload():
    text = Path("nekosuneai/dashboard_runtime_fix_patch.py").read_text(encoding="utf-8")
    assert "Devices & Pairing" in text
    assert "Accept" in text and "Decline" in text
    assert "/api/pairing/pending" in text
    assert "/api/avatar/upload" in text
    assert "Upload VRM" in text


def test_tts_busy_guard_tracks_request_generation():
    text = Path("nekosuneai/tts_busy_guard_patch.py").read_text(encoding="utf-8")
    assert "_neko_busy_generation" in text
    assert "same_turn" in text
    assert "self._release()" in text
    assert '"Ready."' in text


def test_vrm_canvas_remains_transparent():
    text = Path("nekosuneai/static/vrm.html").read_text(encoding="utf-8")
    assert "background:transparent" in text
    assert "renderer.setClearColor(0,0)" in text
