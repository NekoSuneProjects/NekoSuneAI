"""Read-only, token-authenticated LAN status for a Windows BlueStacks worker.

All game inputs still travel through the existing paired Main command queue.
This endpoint exposes no ADB commands, screenshots, or game actions.
"""
from __future__ import annotations

import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread


def serve_status(worker, *, host="127.0.0.1", port=8765, token=""):
    if len(token) < 32:
        raise ValueError("A random LAN status token of at least 32 characters is required")
    if not 1 <= int(port) <= 65535:
        raise ValueError("Invalid status port")

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path != "/v1/lan-game/status":
                self.send_error(404)
                return
            if not hmac.compare_digest(
                    self.headers.get("X-Neko-LAN-Bridge-Token", ""), token):
                self.send_error(403)
                return
            import json
            try:
                detected = worker.device.foreground_package()
                response = {
                    "online": True,
                    "node_id": worker.node_id,
                    "foreground_package": detected,
                    "game_id": worker.package,
                    "game_running": bool(worker.session_id),
                    "paused": worker.paused,
                }
            except Exception:
                response = {"online": False, "node_id": worker.node_id}
            body = json.dumps(response).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    httpd = ThreadingHTTPServer((host, int(port)), Handler)
    thread = Thread(target=httpd.serve_forever, daemon=True,
                    name="nekosuneai-android-lan-status")
    thread.start()
    return httpd
