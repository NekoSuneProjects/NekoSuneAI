from __future__ import annotations

import html
import json
import mimetypes
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .android_devices import AndroidDeviceHub
from .mobile_notify import MobileNotifier
from .webgui import Api, STATIC_DIR


def serve(host: str, port: int, token: str | None = None) -> None:
    api = Api()
    access_token = token or secrets.token_urlsafe(24)
    mobile_notifier = MobileNotifier.from_env()
    android_hub = AndroidDeviceHub()

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

    # Route common natural-language phone requests before the LLM. This applies
    # to typed dashboard requests and to wake-word/voice turns because both pass
    # through Api._pipeline on the Pi-hosted web instance.
    original_pipeline = api._pipeline

    def phone_aware_pipeline(user_text: str, from_voice: bool) -> str:
        lower = user_text.strip().lower()
        devices = android_hub.list_devices()
        device = devices[0] if devices else None

        is_find = any(phrase in lower for phrase in (
            "find my phone", "where is my phone", "ring my phone", "make my phone ring"
        ))
        is_stop = any(phrase in lower for phrase in (
            "stop ringing my phone", "stop my phone ringing", "found my phone", "stop phone ring"
        ))
        is_battery = "phone" in lower and any(word in lower for word in ("battery", "charge", "charging"))
        is_status = "phone" in lower and any(phrase in lower for phrase in ("status", "how is", "performance", "memory"))
        is_notices = "phone" in lower and any(word in lower for word in ("notification", "notifications", "message", "messages", "text", "texts"))

        if not any((is_find, is_stop, is_battery, is_status, is_notices)):
            return original_pipeline(user_text, from_voice)

        user_name = api.profile.get("user_name", "You")
        companion = api.profile.get("companion_name", "NekoSuneAI")
        api._push_chat(user_name, user_text, "user")

        if not device:
            reply = "I can't see an Android companion phone yet. Open NekoSuneAI Companion on the phone and connect it to this Pi first."
        elif is_find:
            android_hub.enqueue(device["device_id"], "FIND_PHONE")
            reply = f"Okay — I'm ringing {device.get('name', 'your phone')} at full ringtone volume until you stop it."
        elif is_stop:
            android_hub.enqueue(device["device_id"], "STOP_RING")
            reply = "Stopped the find-phone ringtone."
        elif is_battery:
            telemetry = device.get("telemetry") or {}
            battery = telemetry.get("battery_percent", "unknown")
            charging = bool(telemetry.get("charging", False))
            reply = f"Your phone battery is {battery}% and it is {'charging' if charging else 'not charging'}."
        elif is_status:
            telemetry = device.get("telemetry") or {}
            reply = (
                f"{device.get('name', 'Your phone')} is {'online' if device.get('online') else 'offline'}. "
                f"Battery {telemetry.get('battery_percent', 'unknown')}%, "
                f"available memory {telemetry.get('memory_available_mb', 'unknown')} MB, "
                f"low-memory flag {'on' if telemetry.get('low_memory') else 'off'}."
            )
        else:
            notices = android_hub.latest_notifications(device["device_id"], 5)
            if not notices:
                reply = "I haven't received any recent phone notifications."
            else:
                summary = "; ".join(
                    f"{n.get('title') or n.get('app') or 'Phone'}: {n.get('text') or 'New notification'}"
                    for n in notices[-5:]
                )
                reply = "Your latest phone notifications are: " + summary

        api._push_chat(companion, reply, "assistant")
        api._push_status("Ready.")
        if api.state.voice_enabled:
            try:
                api._speak_async(reply, "neutral")
            except Exception:
                pass
        return reply

    api._pipeline = phone_aware_pipeline  # type: ignore[method-assign]

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

        def _read_json(self) -> dict:
            length = int(self.headers.get("Content-Length", "0"))
            return json.loads(self.rfile.read(length) or b"{}")

        def do_POST(self):
            if not self._authorized():
                return self._json(401, {"error": "unauthorized"})
            parsed = urlparse(self.path)
            try:
                payload = self._read_json()

                if parsed.path == "/api/rpc":
                    name = str(payload.get("method", ""))
                    if name.startswith("_") or name in {"restart_app"}:
                        raise ValueError("method not allowed")
                    method = getattr(api, name)
                    result = method(*(payload.get("args") or []))
                    return self._json(200, {"result": result})

                if parsed.path == "/api/android/heartbeat":
                    result = android_hub.heartbeat(
                        str(payload.get("device_id", "")),
                        str(payload.get("name", "Android phone")),
                        dict(payload.get("telemetry") or {}),
                    )
                    battery = int((result.get("telemetry") or {}).get("battery_percent", -1))
                    charging = bool((result.get("telemetry") or {}).get("charging", False))
                    if 0 <= battery <= 10 and not charging:
                        api._push_notification(
                            f"{result.get('name', 'Phone')} battery is critically low at {battery}%."
                        )
                    return self._json(200, {"ok": True, "device": result})

                if parsed.path == "/api/android/notification":
                    device_id = str(payload.get("device_id", ""))
                    notice = dict(payload.get("notification") or {})
                    android_hub.add_notification(device_id, notice)
                    title = str(notice.get("title") or notice.get("app") or "Phone")
                    text = str(notice.get("text") or "New notification")
                    api._push_chat("Phone", f"{title}: {text}", "system")
                    return self._json(200, {"ok": True})

                if parsed.path == "/api/android/command":
                    item = android_hub.enqueue(
                        str(payload.get("device_id", "")),
                        str(payload.get("command", "")),
                        dict(payload.get("args") or {}),
                    )
                    return self._json(200, {"ok": True, "command": item})

                return self._json(404, {"error": "not found"})
            except Exception as exc:
                return self._json(400, {"error": str(exc)})

        def do_GET(self):
            parsed = urlparse(self.path)
            query = parse_qs(parsed.query)

            if parsed.path == "/oauth/callback":
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

            if parsed.path == "/api/android/devices":
                if not self._authorized():
                    return self._json(401, {"error": "unauthorized"})
                return self._json(200, {"devices": android_hub.list_devices()})

            if parsed.path == "/api/android/notifications":
                if not self._authorized():
                    return self._json(401, {"error": "unauthorized"})
                return self._json(
                    200,
                    {
                        "notifications": android_hub.latest_notifications(
                            query.get("device_id", [""])[0],
                            int(query.get("limit", ["20"])[0]),
                        )
                    },
                )

            if parsed.path == "/api/android/commands":
                if not self._authorized():
                    return self._json(401, {"error": "unauthorized"})
                commands = android_hub.wait_commands(
                    query.get("device_id", [""])[0],
                    int(query.get("after", ["0"])[0]),
                    float(query.get("wait", ["25"])[0]),
                )
                return self._json(200, {"commands": commands})

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
