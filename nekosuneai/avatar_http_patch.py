from __future__ import annotations

import http.server
import json
import os
from pathlib import Path
from urllib.parse import urlparse

AVATAR_FILE = Path(os.getenv("NEKOSUNEAI_AVATAR_FILE", "/app/data/avatar/current.vrm"))
AVATAR_ROUTE = "/api/avatar/file"
UPLOAD_ROUTE = "/api/avatar/upload"
MANAGER_ROUTES = {"/avatar-upload", "/avatar-upload.html"}
VIEWER_ROUTE = "/avatar"
MAX_VRM_BYTES = 64 * 1024 * 1024
_INSTALLED = False


def _json(handler, code: int, payload: dict) -> None:
    body = json.dumps(payload).encode("utf-8")
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _send_static_html(handler, filename: str) -> None:
    static_dir = Path(__file__).resolve().parent / "static"
    page = static_dir / filename
    if not page.is_file():
        return _json(handler, 404, {"error": f"{filename} is missing"})
    body = page.read_bytes()
    handler.send_response(200)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def install_avatar_http_patch() -> None:
    """Extend the built-in dashboard HTTP server with persistent VRM routes."""
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    AVATAR_FILE.parent.mkdir(parents=True, exist_ok=True)
    if AVATAR_FILE.is_file() and AVATAR_FILE.stat().st_size > 0:
        os.environ.setdefault("VRM_AVATAR_URL", AVATAR_ROUTE)

    original_server = http.server.ThreadingHTTPServer

    class AvatarThreadingHTTPServer(original_server):
        def __init__(self, server_address, RequestHandlerClass, *args, **kwargs):
            base_handler = RequestHandlerClass

            class AvatarHandler(base_handler):
                def do_POST(self):
                    if urlparse(self.path).path != UPLOAD_ROUTE:
                        return super().do_POST()
                    # Avatar management is private even though the read-only
                    # viewer and VRM file are public for embeds/OBS/domain use.
                    if not hasattr(self, "_dashboard_authorized") or not self._dashboard_authorized():
                        return _json(self, 401, {"error": "dashboard authorization required"})
                    try:
                        length = int(self.headers.get("Content-Length", "0"))
                    except ValueError:
                        length = 0
                    if length <= 0:
                        return _json(self, 400, {"error": "VRM file is empty"})
                    if length > MAX_VRM_BYTES:
                        return _json(self, 413, {"error": "VRM file is larger than 64 MB"})
                    filename = self.headers.get("X-Neko-Filename", "avatar.vrm").strip()
                    if not filename.lower().endswith(".vrm"):
                        return _json(self, 400, {"error": "Only .vrm files are accepted"})
                    raw = self.rfile.read(length)
                    if len(raw) < 20 or raw[:4] != b"glTF":
                        return _json(self, 400, {"error": "This does not look like a valid binary VRM/GLB file"})
                    temp = AVATAR_FILE.with_suffix(".vrm.tmp")
                    temp.write_bytes(raw)
                    temp.replace(AVATAR_FILE)
                    os.environ["VRM_AVATAR_URL"] = AVATAR_ROUTE
                    return _json(self, 200, {
                        "ok": True,
                        "filename": filename[:180],
                        "size": len(raw),
                        "url": AVATAR_ROUTE,
                        "message": "VRM saved. Docker dashboard and paired phones will now use this avatar.",
                    })

                def do_GET(self):
                    path = urlparse(self.path).path
                    if path in MANAGER_ROUTES:
                        return _send_static_html(self, "avatar-upload.html")
                    if path == VIEWER_ROUTE:
                        return _send_static_html(self, "vrm.html")
                    if path != AVATAR_ROUTE:
                        return super().do_GET()
                    # Deliberately public: /avatar embeds need this model without
                    # dashboard cookies, query tokens or device credentials.
                    if not AVATAR_FILE.is_file():
                        return _json(self, 404, {"error": "No uploaded VRM avatar"})
                    body = AVATAR_FILE.read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Type", "model/gltf-binary")
                    self.send_header("Cache-Control", "public, no-cache")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)

            super().__init__(server_address, AvatarHandler, *args, **kwargs)

    http.server.ThreadingHTTPServer = AvatarThreadingHTTPServer
