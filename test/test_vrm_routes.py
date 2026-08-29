from pathlib import Path


def test_avatar_http_patch_serves_manager_aliases_and_viewer():
    text = Path("nekosuneai/avatar_http_patch.py").read_text(encoding="utf-8")
    assert 'MANAGER_ROUTES = {"/avatar-upload", "/avatar-upload.html"}' in text
    assert 'VIEWER_ROUTE = "/avatar"' in text
    assert '_send_static_html(self, "vrm.html")' in text
    assert '_send_static_html(self, "avatar-upload.html")' in text


def test_avatar_upload_page_builds_valid_preview_url_and_requires_token():
    text = Path("nekosuneai/static/avatar-upload.html").read_text(encoding="utf-8")
    assert "frame.src='/avatar?'+authParams().toString()" in text
    assert "Dashboard token required" in text
    assert "sessionStorage.getItem('nekoDashboardToken')" in text
    assert "body:f" in text
