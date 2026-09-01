from __future__ import annotations

import http.server
import json
import os
from urllib.parse import urlparse

_INSTALLED = False


def _json(handler, code: int, payload: object) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def install_ntfy_android_patch() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    original_server = http.server.ThreadingHTTPServer

    class NtfyAndroidHTTPServer(original_server):
        def __init__(self, server_address, RequestHandlerClass, *args, **kwargs):
            base_handler = RequestHandlerClass

            class NtfyAndroidHandler(base_handler):
                def do_GET(self):
                    if urlparse(self.path).path != "/api/android/ntfy-config":
                        return super().do_GET()
                    if not hasattr(self, "_device_authorized") or not self._device_authorized():
                        return _json(self, 401, {"error": "paired device authorization required"})

                    enabled = os.getenv("MOBILE_NOTIFY_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
                    public_url = os.getenv("NTFY_BASE_URL", "").strip().rstrip("/")
                    topic = os.getenv("MOBILE_NOTIFY_TOPIC", "").strip()
                    token = os.getenv("MOBILE_NOTIFY_TOKEN", "").strip()
                    usable = enabled and public_url.startswith("https://") and bool(topic)
                    return _json(self, 200, {
                        "enabled": usable,
                        "url": public_url if usable else "",
                        "topic": topic if usable else "",
                        "token": token if usable else "",
                        "requires_https": True,
                    })

            super().__init__(server_address, NtfyAndroidHandler, *args, **kwargs)

    http.server.ThreadingHTTPServer = NtfyAndroidHTTPServer
