from __future__ import annotations

import http.server
import json
import os
from urllib.parse import urlparse

import requests

_INSTALLED = False
_NTFY_PREFIX = "/ntfy"


def _json(handler, code: int, payload: object) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _public_ntfy_url(handler) -> str:
    # ntfy's own NTFY_BASE_URL cannot contain /ntfy. Keep the external
    # NekoSuneAI proxy URL separate so Android can still use one HTTPS domain.
    configured = os.getenv("NTFY_PUBLIC_URL", "").strip().rstrip("/")
    if configured.startswith("https://"):
        return configured

    public_origin = os.getenv("NEKOSUNEAI_PUBLIC_URL", "").strip().rstrip("/")
    if public_origin.startswith("https://"):
        return public_origin + _NTFY_PREFIX

    forwarded_proto = handler.headers.get("X-Forwarded-Proto", "").split(",", 1)[0].strip().lower()
    forwarded_host = handler.headers.get("X-Forwarded-Host", "").split(",", 1)[0].strip()
    host = forwarded_host or handler.headers.get("Host", "").strip()
    if forwarded_proto == "https" and host:
        return f"https://{host}{_NTFY_PREFIX}"
    return ""


def _proxy_ntfy(handler, method: str) -> None:
    parsed = urlparse(handler.path)
    upstream_path = parsed.path[len(_NTFY_PREFIX):] or "/"
    upstream = f"http://127.0.0.1:{os.getenv('NTFY_PORT', '2586')}{upstream_path}"
    if parsed.query:
        upstream += "?" + parsed.query

    headers: dict[str, str] = {}
    for key in ("Accept", "Authorization", "Content-Type", "User-Agent", "Cache-Control"):
        value = handler.headers.get(key)
        if value:
            headers[key] = value
    public_base = _public_ntfy_url(handler)
    if public_base:
        headers["X-Forwarded-Proto"] = "https"
        headers["X-Forwarded-Host"] = urlparse(public_base).netloc
        headers["X-Forwarded-Prefix"] = _NTFY_PREFIX

    body = None
    if method in {"POST", "PUT", "PATCH"}:
        try:
            length = max(0, int(handler.headers.get("Content-Length", "0")))
        except ValueError:
            length = 0
        body = handler.rfile.read(length) if length else b""

    try:
        response = requests.request(
            method,
            upstream,
            headers=headers,
            data=body,
            stream=True,
            timeout=(8, None),
            allow_redirects=False,
        )
    except requests.RequestException as exc:
        return _json(handler, 502, {"error": f"ntfy upstream unavailable: {exc}"})

    with response:
        handler.send_response(response.status_code)
        for key in ("Content-Type", "Cache-Control", "ETag", "Last-Modified", "Content-Disposition"):
            value = response.headers.get(key)
            if value:
                handler.send_header(key, value)
        location = response.headers.get("Location")
        if location:
            if location.startswith("/"):
                location = _NTFY_PREFIX + location
            handler.send_header("Location", location)
        content_length = response.headers.get("Content-Length")
        if content_length:
            handler.send_header("Content-Length", content_length)
        handler.send_header("X-NekoSuneAI-Proxy", "ntfy")
        handler.end_headers()
        if method == "HEAD":
            return
        try:
            for chunk in response.iter_content(chunk_size=8192):
                if not chunk:
                    continue
                handler.wfile.write(chunk)
                handler.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, requests.RequestException):
            pass


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
                    path = urlparse(self.path).path
                    if path == "/api/android/ntfy-config":
                        if not hasattr(self, "_device_authorized") or not self._device_authorized():
                            return _json(self, 401, {"error": "paired device authorization required"})

                        enabled = os.getenv("MOBILE_NOTIFY_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
                        public_url = _public_ntfy_url(self)
                        topic = os.getenv("MOBILE_NOTIFY_TOPIC", "").strip()
                        token = os.getenv("MOBILE_NOTIFY_TOKEN", "").strip()
                        usable = enabled and public_url.startswith("https://") and bool(topic)
                        return _json(self, 200, {
                            "enabled": usable,
                            "url": public_url if usable else "",
                            "topic": topic if usable else "",
                            "token": token if usable else "",
                            "requires_https": True,
                            "shared_domain": True,
                        })
                    if path == _NTFY_PREFIX or path.startswith(_NTFY_PREFIX + "/"):
                        return _proxy_ntfy(self, "GET")
                    return super().do_GET()

                def do_HEAD(self):
                    path = urlparse(self.path).path
                    if path == _NTFY_PREFIX or path.startswith(_NTFY_PREFIX + "/"):
                        return _proxy_ntfy(self, "HEAD")
                    return super().do_HEAD()

                def do_POST(self):
                    path = urlparse(self.path).path
                    if path == _NTFY_PREFIX or path.startswith(_NTFY_PREFIX + "/"):
                        return _proxy_ntfy(self, "POST")
                    return super().do_POST()

            super().__init__(server_address, NtfyAndroidHandler, *args, **kwargs)

    http.server.ThreadingHTTPServer = NtfyAndroidHTTPServer
