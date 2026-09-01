from __future__ import annotations

import base64
import hashlib
import hmac
import html
import http.cookies
import http.server
import os
import secrets
import threading
import time
from urllib.parse import parse_qs, quote, urlparse

_INSTALLED = False
_LOGIN_ATTEMPTS: dict[str, list[float]] = {}
_LOGIN_LOCK = threading.RLock()
_SESSION_COOKIE = "nekosuneai_admin"
_SESSION_TTL = max(900, int(os.getenv("DASHBOARD_SESSION_TTL_SECONDS", "43200")))
_ADMIN_USER = os.getenv("DASHBOARD_ADMIN_USERNAME", "admin").strip() or "admin"
_ADMIN_PASSWORD = os.getenv("DASHBOARD_ADMIN_PASSWORD", "")
_SESSION_SECRET = (os.getenv("DASHBOARD_SESSION_SECRET", "").strip() or secrets.token_urlsafe(48)).encode("utf-8")

LOGIN_HTML = r'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>NekoSuneAI Admin Login</title><style>
:root{color-scheme:dark}*{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;background:radial-gradient(circle at 20% 10%,#24185c 0,#0b0f14 42%,#070a0e 100%);font-family:Inter,Segoe UI,system-ui,sans-serif;color:#f4f7fb}.card{width:min(430px,calc(100vw - 32px));background:rgba(17,24,32,.94);border:1px solid #283548;border-radius:22px;padding:30px;box-shadow:0 24px 80px rgba(0,0,0,.45)}.brand{font-size:26px;font-weight:800}.sub{color:#93a4b7;margin:7px 0 24px}.label{display:block;color:#b9c4d1;font-size:13px;margin:13px 0 7px}.input{width:100%;border:1px solid #2b3849;background:#0d131a;color:#fff;border-radius:12px;padding:13px 14px;outline:none}.input:focus{border-color:#7c5cff;box-shadow:0 0 0 3px rgba(124,92,255,.15)}.btn{width:100%;margin-top:20px;border:0;border-radius:12px;padding:13px;background:#7c5cff;color:#fff;font-weight:800;cursor:pointer}.btn:hover{background:#927cff}.error{border:1px solid #64303a;background:#35171d;color:#ffacb5;border-radius:10px;padding:10px 12px;font-size:13px;margin-bottom:14px}.hint{font-size:12px;color:#708194;margin-top:18px;text-align:center}</style></head><body><form class="card" method="post" action="/login"><div class="brand">NekoSuneAI</div><div class="sub">Administrator dashboard</div>__ERROR__<input type="hidden" name="next" value="__NEXT__"><label class="label">Username</label><input class="input" name="username" autocomplete="username" required autofocus><label class="label">Password</label><input class="input" type="password" name="password" autocomplete="current-password" required><button class="btn" type="submit">Sign in</button><div class="hint">The public avatar viewer stays available without signing in.</div></form></body></html>'''

SESSION_UI = r'''<script id="neko-dashboard-session-ui">(function(){
function clean(u){try{const x=new URL(u,location.origin);if(x.origin!==location.origin)return u;x.searchParams.delete('token');return x.pathname+(x.search?x.search:'')+(x.hash||'')}catch{return u}}
function scrub(){const u=new URL(location.href);if(u.searchParams.has('token')){u.searchParams.delete('token');history.replaceState(null,'',u.pathname+(u.search?u.search:'')+u.hash)}document.querySelectorAll('a[href]').forEach(a=>{const v=a.getAttribute('href')||'';if(v.includes('token='))a.setAttribute('href',clean(v))})}
addEventListener('DOMContentLoaded',()=>{scrub();new MutationObserver(scrub).observe(document.body,{subtree:true,childList:true,attributes:true,attributeFilter:['href']})});setTimeout(scrub,50);
})();</script>'''


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _make_session() -> str:
    payload = f"{int(time.time()) + _SESSION_TTL}:{secrets.token_urlsafe(18)}".encode("utf-8")
    sig = hmac.new(_SESSION_SECRET, payload, hashlib.sha256).digest()
    return _b64(payload) + "." + _b64(sig)


def _valid_session(value: str) -> bool:
    try:
        payload64, sig64 = value.split(".", 1)
        payload = _unb64(payload64)
        sig = _unb64(sig64)
        expected = hmac.new(_SESSION_SECRET, payload, hashlib.sha256).digest()
        if not hmac.compare_digest(sig, expected): return False
        expiry = int(payload.decode("utf-8").split(":", 1)[0])
        return expiry >= int(time.time())
    except Exception:
        return False


def _cookie_value(handler) -> str:
    raw = handler.headers.get("Cookie", "")
    try:
        jar = http.cookies.SimpleCookie(); jar.load(raw)
        morsel = jar.get(_SESSION_COOKIE)
        return morsel.value if morsel else ""
    except Exception:
        return ""


def _secure_cookie(handler) -> bool:
    configured = os.getenv("DASHBOARD_COOKIE_SECURE", "auto").strip().lower()
    if configured in {"1", "true", "yes", "on"}: return True
    if configured in {"0", "false", "no", "off"}: return False
    return handler.headers.get("X-Forwarded-Proto", "").split(",", 1)[0].strip().lower() == "https"


def _set_session_cookie(handler, value: str, *, clear: bool = False) -> None:
    parts = [f"{_SESSION_COOKIE}={value}", "Path=/", "HttpOnly", "SameSite=Lax"]
    if _secure_cookie(handler): parts.append("Secure")
    if clear: parts.extend(["Max-Age=0", "Expires=Thu, 01 Jan 1970 00:00:00 GMT"])
    else: parts.append(f"Max-Age={_SESSION_TTL}")
    handler.send_header("Set-Cookie", "; ".join(parts))


def _login_allowed(ip: str) -> bool:
    now = time.time()
    with _LOGIN_LOCK:
        rows = [x for x in _LOGIN_ATTEMPTS.get(ip, []) if now - x < 300]
        _LOGIN_ATTEMPTS[ip] = rows
        return len(rows) < 8


def _record_failed_login(ip: str) -> None:
    with _LOGIN_LOCK:
        _LOGIN_ATTEMPTS.setdefault(ip, []).append(time.time())


def _render_login(handler, *, error: str = "", next_path: str = "/") -> None:
    safe_next = next_path if next_path.startswith("/") and not next_path.startswith("//") else "/"
    error_html = f'<div class="error">{html.escape(error)}</div>' if error else ""
    body = LOGIN_HTML.replace("__ERROR__", error_html).replace("__NEXT__", html.escape(safe_next, quote=True)).encode("utf-8")
    handler.send_response(200)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers(); handler.wfile.write(body)


def install_dashboard_auth_patch() -> None:
    global _INSTALLED
    if _INSTALLED: return
    _INSTALLED = True
    original_server = http.server.ThreadingHTTPServer

    class DashboardAuthHTTPServer(original_server):
        def __init__(self, server_address, RequestHandlerClass, *args, **kwargs):
            base_handler = RequestHandlerClass

            class DashboardAuthHandler(base_handler):
                def _dashboard_authorized(self) -> bool:
                    if _ADMIN_PASSWORD:
                        return _valid_session(_cookie_value(self))
                    return super()._dashboard_authorized()

                def _device_authorized(self) -> bool:
                    # Read-only avatar config is intentionally public so /avatar
                    # works as a clean domain URL with no cookie or query token.
                    if urlparse(self.path).path == "/api/avatar/config":
                        return True
                    return super()._device_authorized()

                def _redirect(self, target: str) -> None:
                    self.send_response(303); self.send_header("Location", target); self.send_header("Cache-Control", "no-store"); self.end_headers()

                def do_POST(self):
                    if urlparse(self.path).path != "/login": return super().do_POST()
                    if not _ADMIN_PASSWORD: return _render_login(self, error="DASHBOARD_ADMIN_PASSWORD is not configured.")
                    ip = str(self.client_address[0] if self.client_address else "unknown")
                    if not _login_allowed(ip): return _render_login(self, error="Too many failed sign-in attempts. Try again in a few minutes.")
                    try: length = min(max(int(self.headers.get("Content-Length", "0")), 0), 8192)
                    except ValueError: length = 0
                    form = parse_qs(self.rfile.read(length).decode("utf-8", "replace"))
                    username, password = form.get("username", [""])[0], form.get("password", [""])[0]
                    next_path = form.get("next", ["/"])[0]
                    if not (hmac.compare_digest(username, _ADMIN_USER) and hmac.compare_digest(password, _ADMIN_PASSWORD)):
                        _record_failed_login(ip); return _render_login(self, error="Incorrect username or password.", next_path=next_path)
                    self.send_response(303)
                    self.send_header("Location", next_path if next_path.startswith("/") and not next_path.startswith("//") else "/")
                    self.send_header("Cache-Control", "no-store"); _set_session_cookie(self, _make_session()); self.end_headers()

                def do_GET(self):
                    parsed = urlparse(self.path); path = parsed.path
                    if path == "/login":
                        if self._dashboard_authorized(): return self._redirect("/")
                        return _render_login(self, next_path=parse_qs(parsed.query).get("next", ["/"])[0])
                    if path == "/logout":
                        self.send_response(303); self.send_header("Location", "/login"); self.send_header("Cache-Control", "no-store"); _set_session_cookie(self, "", clear=True); self.end_headers(); return
                    if path in {"/avatar", "/api/avatar/file", "/api/avatar/config"}: return super().do_GET()
                    if _ADMIN_PASSWORD and path in {"/", "/index.html", "/automations", "/avatar-upload", "/avatar-upload.html"} and not self._dashboard_authorized():
                        return self._redirect("/login?next=" + quote(path, safe="/"))
                    return super().do_GET()

            super().__init__(server_address, DashboardAuthHandler, *args, **kwargs)

    http.server.ThreadingHTTPServer = DashboardAuthHTTPServer
    try:
        from . import webserver
        webserver.ThreadingHTTPServer = DashboardAuthHTTPServer
        original_decorate = webserver._decorate_dashboard
        if not getattr(original_decorate, "_neko_session_auth", False):
            def decorate(body):
                rendered = original_decorate(body)
                if isinstance(rendered, (bytes, bytearray)):
                    marker = b"</body>"; ui = SESSION_UI.encode("utf-8")
                    return rendered.replace(marker, ui + marker, 1) if marker in rendered else rendered + ui
                marker = "</body>"
                return rendered.replace(marker, SESSION_UI + marker, 1) if marker in rendered else rendered + SESSION_UI
            decorate._neko_session_auth = True
            webserver._decorate_dashboard = decorate
    except Exception:
        pass
