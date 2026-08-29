from __future__ import annotations

import http.server
import json
import os
from pathlib import Path
from urllib.parse import parse_qs, urlparse

AVATAR_FILE = Path(os.getenv("NEKOSUNEAI_AVATAR_FILE", "/app/data/avatar/current.vrm"))
AVATAR_ROUTE = "/api/avatar/file"
UPLOAD_ROUTE = "/api/avatar/upload"
MANAGER_ROUTE = "/avatar-upload"
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
                def _avatar_authorized(self) -> bool:
                    if hasattr(self, "_dashboard_authorized") and self._dashboard_authorized():
                        return True
                    query = parse_qs(urlparse(self.path).query)
                    supplied = query.get("device_token", [""])[0]
                    if not supplied or not hasattr(self, "_device_authorized"):
                        return False
                    previous = self.headers.get("X-Neko-Device-Token")
                    try:
                        if previous is not None:
                            self.headers.replace_header("X-Neko-Device-Token", supplied)
                        else:
                            self.headers["X-Neko-Device-Token"] = supplied
                        return bool(self._device_authorized())
                    finally:
                        if previous is None:
                            try:
                                del self.headers["X-Neko-Device-Token"]
                            except Exception:
                                pass
                        else:
                            self.headers.replace_header("X-Neko-Device-Token", previous)

                def do_POST(self):
                    if urlparse(self.path).path != UPLOAD_ROUTE:
                        return super().do_POST()
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
                    # VRM is a GLB container and begins with the glTF magic bytes.
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
                    if path == MANAGER_ROUTE:
                        if not hasattr(self, "_dashboard_authorized") or not self._dashboard_authorized():
                            return _json(self, 401, {"error": "dashboard authorization required"})
                        static_dir = Path(__file__).resolve().parent / "static"
                        page = static_dir / "avatar-upload.html"
                        if not page.is_file():
                            return _json(self, 404, {"error": "VRM manager page is missing"})
                        body = page.read_bytes()
                        self.send_response(200)
                        self.send_header("Content-Type", "text/html; charset=utf-8")
                        self.send_header("Cache-Control", "no-cache")
                        self.send_header("Content-Length", str(len(body)))
                        self.end_headers()
                        self.wfile.write(body)
                        return
                    if path != AVATAR_ROUTE:
                        return super().do_GET()
                    if not self._avatar_authorized():
                        return _json(self, 401, {"error": "unauthorized"})
                    if not AVATAR_FILE.is_file():
                        return _json(self, 404, {"error": "No uploaded VRM avatar"})
                    body = AVATAR_FILE.read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Type", "model/gltf-binary")
                    self.send_header("Cache-Control", "private, no-cache")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)

            super().__init__(server_address, AvatarHandler, *args, **kwargs)

    http.server.ThreadingHTTPServer = AvatarThreadingHTTPServer
