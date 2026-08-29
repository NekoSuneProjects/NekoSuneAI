from __future__ import annotations

import html
import json
import mimetypes
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .mobile_notify import MobileNotifier
from .webgui import Api, STATIC_DIR


def serve(host: str, port: int, token: str | None = None) -> None:
    api = Api()
    access_token = token or secrets.token_urlsafe(24)
    mobile_notifier = MobileNotifier.from_env()

    # MonitorManager stores this callback during Api.initialize(). Wrapping it
    # here lets Pi-hosted web mode fan warning/danger events out to Android
    # without changing the desktop GUI event contract.
    original_monitor_notification = api._monitor_notification

    def monitor_notification(message: str, level: str = "none") -> None:
        original_monitor_notification(message, level)
        if level in {"warning", "danger"}:
            api._queue_web_event(
                {"type": "mobile_alert", "value": message, "level": level}
            )
        if mobile_notifier:
            mobile_notifier.send(message, level)

    api._monitor_notification = monitor_notification  # type: ignore[method-assign]

    class Handler(BaseHTTPRequestHandler):
        def _authorized(self) -> bool:
            query = parse_qs(urlparse(self.path).query)
            return (
                self.headers.get("X-Neko-Token") == access_token
                or query.get("token", [""])[0] == access_token
            )

        def _json(self, code: int, value) -> None:
            body = json.dumps(value, default=str).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            if not self._authorized():
                return self._json(401, {"error": "unauthorized"})
            if urlparse(self.path).path != "/api/rpc":
                return self._json(404, {"error": "not found"})
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length) or b"{}")
                name = str(payload.get("method", ""))
                if name.startswith("_") or name in {"restart_app"}:
                    raise ValueError("method not allowed")
                method = getattr(api, name)
                result = method(*(payload.get("args") or []))
                self._json(200, {"result": result})
            except Exception as exc:
                self._json(400, {"error": str(exc)})

        def do_GET(self):
            parsed = urlparse(self.path)
            if parsed.path == "/oauth/callback":
                query = parse_qs(parsed.query)
                error = query.get("error", [""])[0]
                result = (
                    {"ok": False, "msg": error}
                    if error
                    else api.complete_mcp_oauth(
                        query.get("state", [""])[0], query.get("code", [""])[0]
                    )
                )
                message = html.escape(str(result.get("msg", "OAuth complete.")))
                body = (
                    "<!doctype html><meta charset='utf-8'><title>NekoSuneAI OAuth</title>"
                    "<body style='background:#080914;color:#f4f2ff;font:18px system-ui;padding:40px'>"
                    f"<h1>{'Connected' if result.get('ok') else 'Connection failed'}</h1><p>{message}</p>"
                    "<script>if(window.opener){window.opener.postMessage({type:'neko-oauth-complete'},location.origin);setTimeout(()=>window.close(),900)}</script></body>"
                ).encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

            if parsed.path == "/api/events":
                if not self._authorized():
                    return self._json(401, {"error": "unauthorized"})
                return self._json(200, {"events": api.get_web_events()})

            # Friendly Android/PWA route. The dashboard token is intentionally
            # not baked into the manifest; mobile.html stores a supplied token
            # in localStorage on the phone instead.
            if parsed.path in {"/mobile", "/mobile/"}:
                relative = "mobile.html"
            else:
                relative = "index.html" if parsed.path in {"", "/"} else parsed.path.lstrip("/")

            target = (STATIC_DIR / relative).resolve()
            if STATIC_DIR.resolve() not in target.parents and target != STATIC_DIR.resolve():
                return self.send_error(403)
            if not target.is_file():
                return self.send_error(404)
            body = target.read_bytes()
            self.send_response(200)
            self.send_header(
                "Content-Type",
                mimetypes.guess_type(target.name)[0] or "application/octet-stream",
            )
            if target.name in {"mobile.html", "mobile-sw.js", "manifest.webmanifest"}:
                self.send_header("Cache-Control", "no-cache")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    print(f"NekoSuneAI web dashboard: http://{host}:{port}/?token={access_token}")
    print(f"NekoSuneAI mobile dashboard: http://{host}:{port}/mobile?token={access_token}")
    if mobile_notifier:
        print(
            "NekoSuneAI Android push: enabled "
            f"({mobile_notifier.base_url}/{mobile_notifier.topic}, min={mobile_notifier.min_level})"
        )
    ThreadingHTTPServer((host, port), Handler).serve_forever()
