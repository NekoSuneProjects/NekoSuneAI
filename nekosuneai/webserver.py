from __future__ import annotations

import html
import json
import mimetypes
import os
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .reminders import ReminderManager
from .scheduled_windows import WindowedMonitorManager
from .webgui import Api, STATIC_DIR
from .youtube_music import YouTubeMusicPlayer, handle_music_request


def _emotion_for(text: str) -> str:
    lowered = (text or "").lower()
    if any(x in lowered for x in ("sorry", "sad", "unfortunately", "miss you")): return "sad"
    if any(x in lowered for x in ("danger", "warning", "angry", "annoying")): return "angry"
    if any(x in lowered for x in ("wow", "amazing", "exciting", "great!", "awesome")): return "excited"
    if any(x in lowered for x in ("happy", "glad", "nice", "great", "done", "okay")): return "happy"
    return "neutral"


def _decorate_dashboard(body: bytes) -> bytes:
    """Replace only the large dashboard logo with the live VRM stage.

    The original static file stays lightweight and update-friendly. Small
    loading/sidebar logos remain images, while the central companion stage is
    upgraded at serve time.
    """
    text = body.decode("utf-8")
    old = '<img src="logo.png" alt="NekoSuneAI avatar" class="avatar-logo relative z-10 w-40 h-40 object-contain" draggable="false">'
    new = '<iframe id="vrm-avatar-frame" src="about:blank" title="NekoSuneAI VRM avatar" class="relative z-10 w-full h-[220px] border-0 bg-transparent" allow="autoplay"></iframe>'
    text = text.replace(old, new, 1)
    bridge = r'''<script>
(function(){
  const frame=()=>document.getElementById('vrm-avatar-frame');
  const boot=()=>{const f=frame();if(f&&f.src==='about:blank')f.src='/avatar'+location.search};
  window.nekoAvatarEmotion=e=>{try{frame()?.contentWindow?.postMessage({type:'neko-emotion',emotion:e||'neutral'},location.origin)}catch(_){}};
  window.nekoAvatarSpeaking=a=>{try{frame()?.contentWindow?.postMessage({type:'neko-speaking',active:!!a},location.origin)}catch(_){}};
  addEventListener('DOMContentLoaded',boot); setTimeout(boot,50);
  const originalFetch=window.fetch.bind(window);
  window.fetch=async function(...args){
    const response=await originalFetch(...args);
    try{
      const u=String(args[0]||'');
      if(u.includes('/api/events')){
        const j=await response.clone().json();
        for(const e of (j.events||[])){
          if(e.type==='avatar_emotion')window.nekoAvatarEmotion(e.value);
          if(e.type==='avatar_speaking')window.nekoAvatarSpeaking(e.value);
          if(e.type==='status'&&String(e.value||'').toLowerCase().includes('ready'))window.nekoAvatarSpeaking(false);
        }
      }
    }catch(_){}
    return response;
  };
})();
</script>'''
    return text.replace("</body>", bridge + "</body>", 1).encode("utf-8")


def serve(host: str, port: int, token: str | None = None) -> None:
    api = Api()
    access_token = token or secrets.token_urlsafe(24)
    music = YouTubeMusicPlayer(lambda msg: api._push_chat("Music", msg, "system"))
    windowed_monitor: WindowedMonitorManager | None = None
    reminders: ReminderManager | None = None

    original_initialize = api.initialize
    def initialize_with_services(*args, **kwargs):
        nonlocal windowed_monitor, reminders
        result = original_initialize(*args, **kwargs)
        if windowed_monitor is None:
            windowed_monitor = WindowedMonitorManager(api.config, api._monitor_notification); windowed_monitor.start()
        if reminders is None:
            reminders = ReminderManager(api._monitor_notification, getattr(api.config, "timezone", None) or "Europe/London"); reminders.start()
        return result
    api.initialize = initialize_with_services  # type: ignore[method-assign]

    original_pipeline = api._pipeline
    def pi_feature_pipeline(user_text: str, from_voice: bool) -> str:
        nonlocal windowed_monitor, reminders
        reply = None
        try: reply = handle_music_request(user_text, music)
        except Exception as exc: reply = f"I couldn't use YouTube music: {exc}"
        if reply is None and reminders is not None:
            try: reply = reminders.handle(user_text)
            except Exception as exc: reply = f"I couldn't create that reminder: {exc}"
        if reply is None and windowed_monitor is not None:
            try: reply = windowed_monitor.handle(user_text)
            except Exception as exc: reply = f"I couldn't create that monitoring schedule: {exc}"
        if reply is None:
            reply = original_pipeline(user_text, from_voice)
            try: api._queue_web_event({"type":"avatar_emotion","value":_emotion_for(reply)})
            except Exception: pass
            return reply

        user_name = api.profile.get("user_name", "You"); companion = api.profile.get("companion_name", "NekoSuneAI")
        api._push_chat(user_name, user_text, "user"); api._push_chat(companion, reply, "assistant"); api._push_status("Ready.")
        try: api._queue_web_event({"type":"avatar_emotion","value":_emotion_for(reply)})
        except Exception: pass
        if api.state.voice_enabled and not reply.lower().startswith("playing"):
            try: api._queue_web_event({"type":"avatar_speaking","value":True}); api._speak_async(reply, "neutral")
            except Exception: pass
        return reply
    api._pipeline = pi_feature_pipeline  # type: ignore[method-assign]

    class Handler(BaseHTTPRequestHandler):
        def _authorized(self) -> bool:
            query = parse_qs(urlparse(self.path).query)
            return self.headers.get("X-Neko-Token") == access_token or query.get("token", [""])[0] == access_token

        def _json(self, code: int, value) -> None:
            body = json.dumps(value, default=str).encode(); self.send_response(code)
            self.send_header("Content-Type", "application/json"); self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)

        def do_POST(self):
            if not self._authorized(): return self._json(401, {"error":"unauthorized"})
            if urlparse(self.path).path != "/api/rpc": return self._json(404, {"error":"not found"})
            try:
                length = int(self.headers.get("Content-Length", "0")); payload = json.loads(self.rfile.read(length) or b"{}")
                name = str(payload.get("method", ""))
                if name.startswith("_") or name in {"restart_app"}: raise ValueError("method not allowed")
                method = getattr(api, name); result = method(*(payload.get("args") or [])); self._json(200, {"result": result})
            except Exception as exc: self._json(400, {"error": str(exc)})

        def do_GET(self):
            parsed = urlparse(self.path)
            if parsed.path == "/oauth/callback":
                query = parse_qs(parsed.query); error = query.get("error", [""])[0]
                result = ({"ok": False, "msg": error} if error else api.complete_mcp_oauth(query.get("state", [""])[0], query.get("code", [""])[0]))
                message = html.escape(str(result.get("msg", "OAuth complete.")))
                body = ("<!doctype html><meta charset='utf-8'><title>NekoSuneAI OAuth</title><body style='background:#080914;color:#f4f2ff;font:18px system-ui;padding:40px'>" f"<h1>{'Connected' if result.get('ok') else 'Connection failed'}</h1><p>{message}</p>" "<script>if(window.opener){window.opener.postMessage({type:'neko-oauth-complete'},location.origin);setTimeout(()=>window.close(),900)}</script></body>").encode()
                self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body); return
            if parsed.path == "/api/events":
                if not self._authorized(): return self._json(401, {"error":"unauthorized"})
                return self._json(200, {"events": api.get_web_events()})
            if parsed.path == "/api/avatar/config":
                if not self._authorized(): return self._json(401, {"error":"unauthorized"})
                return self._json(200, {"url": os.getenv("VRM_AVATAR_URL", "").strip(), "companion": api.profile.get("companion_name", "NekoSuneAI")})
            if parsed.path in {"/avatar", "/avatar/"}: relative = "vrm.html"
            else: relative = "index.html" if parsed.path in {"", "/"} else parsed.path.lstrip("/")
            target = (STATIC_DIR / relative).resolve()
            if STATIC_DIR.resolve() not in target.parents and target != STATIC_DIR.resolve(): return self.send_error(403)
            if not target.is_file(): return self.send_error(404)
            body = target.read_bytes()
            if target.name == "index.html": body = _decorate_dashboard(body)
            self.send_response(200); self.send_header("Content-Type", mimetypes.guess_type(target.name)[0] or "application/octet-stream")
            if target.name in {"vrm.html", "index.html"}: self.send_header("Cache-Control", "no-cache")
            self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)

        def log_message(self, *_args): pass

    print(f"NekoSuneAI web dashboard: http://{host}:{port}/?token={access_token}")
    print(f"NekoSuneAI VRM avatar: http://{host}:{port}/avatar?token={access_token}")
    ThreadingHTTPServer((host, port), Handler).serve_forever()
