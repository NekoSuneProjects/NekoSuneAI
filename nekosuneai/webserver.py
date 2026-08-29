from __future__ import annotations

import base64
import html
import json
import mimetypes
import os
import secrets
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .avatar_motion import drive_tts_avatar
from .local_affect import LocalAffectDetector
from .mood_state import load_mood, update_from_interaction
from .owner_learning import learn_from_text, list_profile, summary_for_prompt
from .reminders import ReminderManager
from .scheduled_windows import WindowedMonitorManager
from .support_checkins import SupportCheckinManager, support_context
from .vision import describe_image, strip_data_uri
from .voice_tone import analyze_voice_wav
from .webgui import Api, STATIC_DIR
from .youtube_music import YouTubeMusicPlayer, handle_music_request

VISION_PROMPT = (
    "Describe the visible scene briefly for a conversational assistant. Focus on non-sensitive facts: "
    "objects, posture, visible facial expression such as smiling only when obvious, gestures, and what the "
    "person appears to be doing. Do not identify people and do not infer health, race, religion, sexuality, "
    "politics, disability, or other sensitive traits."
)


def _decorate_dashboard(body: bytes) -> bytes:
    text = body.decode("utf-8")
    old = '<img src="logo.png" alt="NekoSuneAI avatar" class="avatar-logo relative z-10 w-40 h-40 object-contain" draggable="false">'
    new = '<iframe id="vrm-avatar-frame" src="about:blank" title="NekoSuneAI VRM avatar" class="relative z-10 w-full h-[220px] border-0 bg-transparent" allow="autoplay"></iframe>'
    text = text.replace(old, new, 1)
    bridge = r'''<script>
(function(){
  const frame=()=>document.getElementById('vrm-avatar-frame');
  const boot=()=>{const f=frame();if(f&&f.src==='about:blank')f.src='/avatar'+location.search};
  const post=m=>{try{frame()?.contentWindow?.postMessage(m,location.origin)}catch(_){}};
  window.nekoAvatarEmotion=e=>post({type:'neko-emotion',emotion:e||'neutral'});
  window.nekoAvatarSpeaking=a=>post({type:'neko-speaking',active:!!a});
  window.nekoAvatarViseme=v=>post({type:'neko-viseme',name:v?.name||'',weight:Number(v?.weight||0)});
  window.nekoAvatarGesture=g=>post({type:'neko-gesture',gesture:g||'idle'});
  addEventListener('DOMContentLoaded',boot);setTimeout(boot,50);
  const originalFetch=window.fetch.bind(window);
  window.fetch=async function(...args){
    const response=await originalFetch(...args);
    try{
      const u=String(args[0]||'');
      if(u.includes('/api/events')){
        const j=await response.clone().json();
        for(const e of(j.events||[])){
          if(e.type==='avatar_emotion')window.nekoAvatarEmotion(e.value);
          if(e.type==='avatar_speaking')window.nekoAvatarSpeaking(e.value);
          if(e.type==='avatar_viseme')window.nekoAvatarViseme(e.value);
          if(e.type==='avatar_gesture')window.nekoAvatarGesture(e.value);
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
    affect = LocalAffectDetector()
    support = SupportCheckinManager()
    vision_context: dict[str, object] = {"text": "", "epoch": 0.0, "source": ""}
    voice_context: dict[str, object] = {"text": "", "epoch": 0.0}

    def emit_avatar(event: dict) -> None:
        try:
            api._queue_web_event(event)
        except Exception:
            pass

    original_initialize = api.initialize

    def initialize_with_services(*args, **kwargs):
        nonlocal windowed_monitor, reminders
        result = original_initialize(*args, **kwargs)
        if windowed_monitor is None:
            windowed_monitor = WindowedMonitorManager(api.config, api._monitor_notification)
            windowed_monitor.start()
        if reminders is None:
            reminders = ReminderManager(api._monitor_notification, getattr(api.config, "timezone", None) or "Europe/London")
            reminders.start()
        return result

    api.initialize = initialize_with_services  # type: ignore[method-assign]
    original_pipeline = api._pipeline

    def pi_feature_pipeline(user_text: str, from_voice: bool) -> str:
        nonlocal windowed_monitor, reminders
        learn_from_text(user_text)
        mood = update_from_interaction(user_text)
        emit_avatar({"type": "avatar_emotion", "value": mood.expression()})
        emit_avatar({"type": "avatar_gesture", "value": mood.gesture()})

        reply = None
        try:
            reply = handle_music_request(user_text, music)
        except Exception as exc:
            reply = f"I couldn't use YouTube music: {exc}"
        if reply is None and reminders is not None:
            try:
                reply = reminders.handle(user_text)
            except Exception as exc:
                reply = f"I couldn't create that reminder: {exc}"
        if reply is None and windowed_monitor is not None:
            try:
                reply = windowed_monitor.handle(user_text)
            except Exception as exc:
                reply = f"I couldn't create that monitoring schedule: {exc}"

        context_blocks: list[str] = []
        if time.time() - float(vision_context.get("epoch") or 0) <= 20 and vision_context.get("text"):
            context_blocks.append("Opt-in current camera/Kinect context: " + str(vision_context["text"]))
        if time.time() - float(voice_context.get("epoch") or 0) <= 30 and voice_context.get("text"):
            context_blocks.append("Tentative current voice-tone cue: " + str(voice_context["text"]))
        owner_summary = summary_for_prompt()
        if owner_summary:
            context_blocks.append(owner_summary)
        pipeline_text = user_text
        if context_blocks:
            pipeline_text += "\n\n[Companion context — uncertain cues must never override the user's own words:\n" + "\n".join(context_blocks) + "]"

        if reply is None:
            reply = original_pipeline(pipeline_text, from_voice)
            if getattr(api.state, "voice_enabled", False) or from_voice:
                drive_tts_avatar(reply, emit_avatar, gesture=mood.gesture())
            return reply

        user_name = api.profile.get("user_name", "You")
        companion = api.profile.get("companion_name", "NekoSuneAI")
        api._push_chat(user_name, user_text, "user")
        api._push_chat(companion, reply, "assistant")
        api._push_status("Ready.")
        if api.state.voice_enabled and not reply.lower().startswith("playing"):
            try:
                drive_tts_avatar(reply, emit_avatar, gesture=mood.gesture())
                api._speak_async(reply, mood.expression())
            except Exception:
                pass
        return reply

    api._pipeline = pi_feature_pipeline  # type: ignore[method-assign]

    class Handler(BaseHTTPRequestHandler):
        def _authorized(self) -> bool:
            query = parse_qs(urlparse(self.path).query)
            return self.headers.get("X-Neko-Token") == access_token or query.get("token", [""])[0] == access_token

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
            parsed = urlparse(self.path)
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length > 1_800_000:
                    raise ValueError("request too large")
                payload = json.loads(self.rfile.read(length) or b"{}")

                if parsed.path in {"/api/android/vision", "/api/vision/frame"}:
                    api.initialize()
                    image = strip_data_uri(str(payload.get("image_base64", "")))
                    if not image:
                        raise ValueError("image_base64 is required")
                    cue = affect.detect(image)
                    description = describe_image(api.config, image, VISION_PROMPT)
                    context_parts: list[str] = []
                    if description:
                        context_parts.append(description[:900])
                    if cue:
                        context_parts.append(support_context(cue))
                    if not context_parts:
                        detail = f" Local affect fallback: {affect.error}." if affect.error else ""
                        raise ValueError("No configured vision model or local affect fallback could analyse this frame." + detail)
                    combined = " ".join(context_parts)
                    vision_context.update({"text": combined[:1600], "epoch": time.time(), "source": str(payload.get("source", "camera"))[:40]})
                    emit_avatar({"type": "vision_context", "value": combined[:500]})
                    checkin = support.observe(cue)
                    if checkin:
                        companion = api.profile.get("companion_name", "NekoSuneAI")
                        api._push_chat(companion, checkin, "assistant")
                        api._push_status("Checking in with you.")
                        emit_avatar({"type": "avatar_emotion", "value": "relaxed"})
                        emit_avatar({"type": "avatar_gesture", "value": "relaxed"})
                        if getattr(api.state, "voice_enabled", False):
                            try:
                                drive_tts_avatar(checkin, emit_avatar, gesture="relaxed")
                                api._speak_async(checkin, "gentle")
                            except Exception:
                                pass
                    return self._json(200, {"ok": True, "description": description or "", "affect": None if cue is None else {"label": cue.label, "confidence": round(cue.confidence, 4), "tentative": True}, "checkin": checkin or "", "local_affect_available": affect.available})

                if parsed.path in {"/api/android/voice-tone", "/api/voice/tone"}:
                    raw = str(payload.get("wav_base64", ""))
                    if "," in raw:
                        raw = raw.split(",", 1)[1]
                    try:
                        wav = base64.b64decode(raw)
                    except Exception as exc:
                        raise ValueError("invalid wav_base64") from exc
                    cue = analyze_voice_wav(wav)
                    if cue is None:
                        raise ValueError("A short PCM16 WAV utterance is required")
                    voice_context.update({"text": f"{cue.label} (confidence {cue.confidence:.2f}); acoustic cue only, not proof of emotion", "epoch": time.time()})
                    return self._json(200, {"ok": True, "tone": cue.as_dict(), "tentative": True})

                if parsed.path == "/api/android/chat":
                    api.initialize()
                    message = str(payload.get("message", "")).strip()
                    if not message:
                        raise ValueError("message is required")
                    reply = api._pipeline(message, False)
                    mood = load_mood()
                    return self._json(200, {"reply": reply, "emotion": mood.expression(), "gesture": mood.gesture()})

                if parsed.path != "/api/rpc":
                    return self._json(404, {"error": "not found"})
                name = str(payload.get("method", ""))
                if name.startswith("_") or name in {"restart_app"}:
                    raise ValueError("method not allowed")
                method = getattr(api, name)
                result = method(*(payload.get("args") or []))
                return self._json(200, {"result": result})
            except Exception as exc:
                return self._json(400, {"error": str(exc)})

        def do_GET(self):
            parsed = urlparse(self.path)
            if parsed.path == "/oauth/callback":
                query = parse_qs(parsed.query)
                error = query.get("error", [""])[0]
                result = ({"ok": False, "msg": error} if error else api.complete_mcp_oauth(query.get("state", [""])[0], query.get("code", [""])[0]))
                message = html.escape(str(result.get("msg", "OAuth complete.")))
                body = ("<!doctype html><meta charset='utf-8'><title>NekoSuneAI OAuth</title><body style='background:#080914;color:#f4f2ff;font:18px system-ui;padding:40px'>" f"<h1>{'Connected' if result.get('ok') else 'Connection failed'}</h1><p>{message}</p>" "<script>if(window.opener){window.opener.postMessage({type:'neko-oauth-complete'},location.origin);setTimeout(()=>window.close(),900)}</script></body>").encode()
                self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body); return
            if parsed.path == "/api/events":
                if not self._authorized(): return self._json(401, {"error":"unauthorized"})
                return self._json(200, {"events": api.get_web_events()})
            if parsed.path == "/api/owner/profile":
                if not self._authorized(): return self._json(401, {"error":"unauthorized"})
                return self._json(200, {"items": list_profile()})
            if parsed.path == "/api/avatar/config":
                if not self._authorized(): return self._json(401, {"error":"unauthorized"})
                api.initialize(); mood = load_mood()
                return self._json(200, {"url": os.getenv("VRM_AVATAR_URL", "").strip(), "companion": api.profile.get("companion_name", "NekoSuneAI"), "mood": mood.expression(), "gesture": mood.gesture(), "mood_state": {"valence": round(mood.valence,3), "arousal": round(mood.arousal,3), "trust": round(mood.trust,3), "caution": round(mood.caution,3)}, "local_affect_available": affect.available, "local_affect_error": affect.error if not affect.available else ""})
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
