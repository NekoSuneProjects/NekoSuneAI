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

from .android_devices import AndroidDeviceHub
from .avatar_motion import drive_tts_avatar
from .device_pairing import DevicePairingManager, MdnsAdvertiser
from .local_affect import LocalAffectDetector
from .mobile_notify import MobileNotifier
from .mood_state import load_mood, update_from_interaction
from .owner_learning import learn_from_text, list_profile, summary_for_prompt
from .reminders import ReminderManager
from .scheduled_windows import WindowedMonitorManager
from .support_checkins import SupportCheckinManager, support_context
from .vision import describe_image, strip_data_uri
from .voice_tone import analyze_voice_wav, load_latest
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

  const token=()=>new URLSearchParams(location.search).get('token')||'';
  const pairFetch=(url,options={})=>originalFetch(url,{...options,headers:{...(options.headers||{}),'X-Neko-Token':token(),'Content-Type':'application/json'}});
  function escapeHtml(v){return String(v||'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
  function mountPairing(){
    if(document.getElementById('neko-pairing-panel'))return;
    const panel=document.createElement('section');
    panel.id='neko-pairing-panel';
    panel.className='card fixed right-4 bottom-4 z-[100] w-[min(390px,calc(100vw-2rem))] p-4 hidden';
    panel.innerHTML=`<div class="flex items-center justify-between gap-3 mb-2"><div><div class="section-kicker">ANDROID COMPANION</div><div class="text-[15px] font-bold text-nova-text mt-1">Device pairing request</div></div><span class="live-pill">LAN</span></div><div class="text-[11px] text-nova-muted2 mb-3">A phone found this NekoSuneAI server. Approve only devices you recognize.</div><div id="neko-pairing-list" class="space-y-2"></div>`;
    document.body.appendChild(panel);
  }
  async function pairingAction(requestId,action){
    try{await pairFetch('/api/pairing/'+action,{method:'POST',body:JSON.stringify({request_id:requestId})});await refreshPairing();}catch(_){}
  }
  async function refreshPairing(){
    mountPairing();
    const panel=document.getElementById('neko-pairing-panel'),list=document.getElementById('neko-pairing-list');
    if(!panel||!list||!token()){if(panel)panel.classList.add('hidden');return;}
    try{
      const r=await pairFetch('/api/pairing/pending');
      if(!r.ok){panel.classList.add('hidden');return;}
      const j=await r.json(),items=j.pending||[];
      if(!items.length){panel.classList.add('hidden');return;}
      panel.classList.remove('hidden');
      list.innerHTML=items.map(x=>`<div class="card-alt p-3"><div class="text-[13px] font-semibold text-nova-text">${escapeHtml(x.name)}</div><div class="text-[10px] text-nova-muted mt-1">${escapeHtml(x.remote_ip)} · ${escapeHtml(x.device_id).slice(0,18)}…</div><div class="flex gap-2 mt-3"><button class="btn-primary rounded-lg px-3 py-2 text-[11px] flex-1" data-pair-approve="${escapeHtml(x.request_id)}">Approve</button><button class="btn-danger rounded-lg px-3 py-2 text-[11px] flex-1" data-pair-reject="${escapeHtml(x.request_id)}">Reject</button></div></div>`).join('');
      list.querySelectorAll('[data-pair-approve]').forEach(b=>b.onclick=()=>pairingAction(b.dataset.pairApprove,'approve'));
      list.querySelectorAll('[data-pair-reject]').forEach(b=>b.onclick=()=>pairingAction(b.dataset.pairReject,'reject'));
    }catch(_){panel.classList.add('hidden');}
  }
  addEventListener('DOMContentLoaded',()=>{mountPairing();refreshPairing();setInterval(refreshPairing,3000)});
})();
</script>'''
    return text.replace("</body>", bridge + "</body>", 1).encode("utf-8")


def serve(host: str, port: int, token: str | None = None) -> None:
    api = Api()
    access_token = token or secrets.token_urlsafe(24)
    music = YouTubeMusicPlayer(lambda msg: api._push_chat("Music", msg, "system"))
    mobile_notifier = MobileNotifier.from_env()
    android_hub = AndroidDeviceHub()
    pairing = DevicePairingManager()
    advertiser = MdnsAdvertiser(port)
    windowed_monitor: WindowedMonitorManager | None = None
    reminders: ReminderManager | None = None
    affect = LocalAffectDetector()
    support = SupportCheckinManager()
    vision_context: dict[str, object] = {"text": "", "epoch": 0.0, "source": ""}

    original_monitor_notification = api._monitor_notification

    def monitor_notification(message: str, level: str = "none") -> None:
        original_monitor_notification(message, level)
        if level in {"warning", "danger"}:
            api._queue_web_event({"type": "mobile_alert", "value": message, "level": level})
        if mobile_notifier:
            mobile_notifier.send(message, level)

    api._monitor_notification = monitor_notification  # type: ignore[method-assign]

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

    def integrated_pipeline(user_text: str, from_voice: bool) -> str:
        nonlocal windowed_monitor, reminders
        learn_from_text(user_text)
        mood = update_from_interaction(user_text)
        emit_avatar({"type": "avatar_emotion", "value": mood.expression()})
        emit_avatar({"type": "avatar_gesture", "value": mood.gesture()})

        lower = user_text.strip().lower()
        devices = android_hub.list_devices()
        device = devices[0] if devices else None
        is_find = any(p in lower for p in ("find my phone", "where is my phone", "ring my phone", "make my phone ring"))
        is_stop = any(p in lower for p in ("stop ringing my phone", "stop my phone ringing", "found my phone", "stop phone ring"))
        is_battery = "phone" in lower and any(w in lower for w in ("battery", "charge", "charging"))
        is_status = "phone" in lower and any(p in lower for p in ("status", "how is", "performance", "memory"))
        is_notices = "phone" in lower and any(w in lower for w in ("notification", "notifications", "message", "messages", "text", "texts"))

        reply = None
        if any((is_find, is_stop, is_battery, is_status, is_notices)):
            if not device:
                reply = "I can't see an Android companion phone yet. Open NekoSuneAI Companion on the phone and pair it with this Pi first."
            elif is_find:
                android_hub.enqueue(device["device_id"], "FIND_PHONE")
                reply = f"Okay — I'm ringing {device.get('name', 'your phone')} at full ringtone volume until you stop it."
            elif is_stop:
                android_hub.enqueue(device["device_id"], "STOP_RING")
                reply = "Stopped the find-phone ringtone."
            elif is_battery:
                telemetry = device.get("telemetry") or {}
                reply = f"Your phone battery is {telemetry.get('battery_percent', 'unknown')}% and it is {'charging' if telemetry.get('charging') else 'not charging'}."
            elif is_status:
                telemetry = device.get("telemetry") or {}
                reply = (
                    f"{device.get('name', 'Your phone')} is {'online' if device.get('online') else 'offline'}. "
                    f"Battery {telemetry.get('battery_percent', 'unknown')}%, available memory "
                    f"{telemetry.get('memory_available_mb', 'unknown')} MB, low-memory flag "
                    f"{'on' if telemetry.get('low_memory') else 'off'}."
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

        if reply is None:
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
        tone = load_latest(30)
        if tone is not None:
            context_blocks.append(
                f"Tentative current voice-tone cue: {tone.label} (confidence {tone.confidence:.2f}); acoustic cue only, not proof of emotion"
            )
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

    api._pipeline = integrated_pipeline  # type: ignore[method-assign]

    class Handler(BaseHTTPRequestHandler):
        def _dashboard_authorized(self) -> bool:
            query = parse_qs(urlparse(self.path).query)
            return self.headers.get("X-Neko-Token") == access_token or query.get("token", [""])[0] == access_token

        def _device_authorized(self) -> bool:
            if self._dashboard_authorized():
                return True
            supplied = self.headers.get("X-Neko-Device-Token", "")
            return bool(supplied) and (secrets.compare_digest(supplied, access_token) or pairing.authorize_device_token(supplied))

        def _authorized(self) -> bool:
            return self._dashboard_authorized()

        def _json(self, code: int, value) -> None:
            body = json.dumps(value, default=str).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            parsed = urlparse(self.path)
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length > 1_800_000:
                    raise ValueError("request too large")
                payload = json.loads(self.rfile.read(length) or b"{}")

                if parsed.path == "/api/pairing/request":
                    try:
                        item = pairing.request(
                            str(payload.get("device_id", "")),
                            str(payload.get("name", "Android phone")),
                            str(self.client_address[0]),
                        )
                    except PermissionError as exc:
                        return self._json(403, {"error": str(exc)})
                    api._push_notification(f"Pairing request from {item.get('name', 'Android phone')} ({item.get('remote_ip', '')}). Approve it on the dashboard.")
                    return self._json(200, {"ok": True, **item})

                if parsed.path in {"/api/pairing/approve", "/api/pairing/reject", "/api/pairing/revoke"}:
                    if not self._dashboard_authorized():
                        return self._json(401, {"error": "unauthorized"})
                    if parsed.path == "/api/pairing/approve":
                        result = pairing.approve(str(payload.get("request_id", "")))
                        api._push_notification(f"Paired {result.get('name', 'Android phone')} successfully.")
                    elif parsed.path == "/api/pairing/reject":
                        result = pairing.reject(str(payload.get("request_id", "")))
                    else:
                        result = pairing.revoke(str(payload.get("device_id", "")))
                    return self._json(200, result)

                device_paths = {
                    "/api/android/heartbeat", "/api/android/notification", "/api/android/command",
                    "/api/android/vision", "/api/vision/frame", "/api/android/voice-tone",
                    "/api/voice/tone", "/api/android/chat",
                }
                if parsed.path in device_paths:
                    if not self._device_authorized():
                        return self._json(401, {"error": "unauthorized"})
                elif not self._dashboard_authorized():
                    return self._json(401, {"error": "unauthorized"})

                if parsed.path == "/api/android/heartbeat":
                    result = android_hub.heartbeat(
                        str(payload.get("device_id", "")), str(payload.get("name", "Android phone")), dict(payload.get("telemetry") or {})
                    )
                    battery = int((result.get("telemetry") or {}).get("battery_percent", -1))
                    charging = bool((result.get("telemetry") or {}).get("charging", False))
                    if 0 <= battery <= 10 and not charging:
                        api._push_notification(f"{result.get('name', 'Phone')} battery is critically low at {battery}%.")
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
                        str(payload.get("device_id", "")), str(payload.get("command", "")), dict(payload.get("args") or {})
                    )
                    return self._json(200, {"ok": True, "command": item})

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
                                api._speak_async(checkin, "relaxed")
                            except Exception:
                                pass
                    return self._json(200, {
                        "ok": True,
                        "description": description or "",
                        "affect": None if cue is None else {"label": cue.label, "confidence": round(cue.confidence, 4), "tentative": True},
                        "checkin": checkin or "",
                        "local_affect_available": affect.available,
                    })

                if parsed.path in {"/api/android/voice-tone", "/api/voice/tone"}:
                    raw = str(payload.get("wav_base64", ""))
                    raw = raw.split(",", 1)[1] if "," in raw else raw
                    try:
                        wav = base64.b64decode(raw)
                    except Exception as exc:
                        raise ValueError("invalid wav_base64") from exc
                    cue = analyze_voice_wav(wav)
                    if cue is None:
                        raise ValueError("A short PCM16 WAV utterance is required")
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
            query = parse_qs(parsed.query)
            if parsed.path == "/oauth/callback":
                error = query.get("error", [""])[0]
                result = ({"ok": False, "msg": error} if error else api.complete_mcp_oauth(query.get("state", [""])[0], query.get("code", [""])[0]))
                message = html.escape(str(result.get("msg", "OAuth complete.")))
                body = ("<!doctype html><meta charset='utf-8'><title>NekoSuneAI OAuth</title><body style='background:#080914;color:#f4f2ff;font:18px system-ui;padding:40px'>" f"<h1>{'Connected' if result.get('ok') else 'Connection failed'}</h1><p>{message}</p>" "<script>if(window.opener){window.opener.postMessage({type:'neko-oauth-complete'},location.origin);setTimeout(()=>window.close(),900)}</script></body>").encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if parsed.path == "/api/pairing/status":
                return self._json(200, pairing.status(query.get("request_id", [""])[0], query.get("device_id", [""])[0]))
            if parsed.path == "/api/pairing/pending":
                if not self._dashboard_authorized():
                    return self._json(401, {"error": "unauthorized"})
                return self._json(200, {"pending": pairing.pending()})
            if parsed.path == "/api/pairing/paired":
                if not self._dashboard_authorized():
                    return self._json(401, {"error": "unauthorized"})
                return self._json(200, {"paired": pairing.paired()})
            if parsed.path == "/api/events":
                if not self._dashboard_authorized():
                    return self._json(401, {"error": "unauthorized"})
                return self._json(200, {"events": api.get_web_events()})
            if parsed.path == "/api/android/devices":
                if not self._device_authorized():
                    return self._json(401, {"error": "unauthorized"})
                return self._json(200, {"devices": android_hub.list_devices()})
            if parsed.path == "/api/android/notifications":
                if not self._device_authorized():
                    return self._json(401, {"error": "unauthorized"})
                return self._json(200, {"notifications": android_hub.latest_notifications(query.get("device_id", [""])[0], int(query.get("limit", ["20"])[0]))})
            if parsed.path == "/api/android/commands":
                if not self._device_authorized():
                    return self._json(401, {"error": "unauthorized"})
                commands = android_hub.wait_commands(
                    query.get("device_id", [""])[0], int(query.get("after", ["0"])[0]), float(query.get("wait", ["25"])[0])
                )
                return self._json(200, {"commands": commands})
            if parsed.path == "/api/owner/profile":
                if not self._dashboard_authorized():
                    return self._json(401, {"error": "unauthorized"})
                return self._json(200, {"items": list_profile()})
            if parsed.path == "/api/avatar/config":
                if not self._device_authorized():
                    return self._json(401, {"error": "unauthorized"})
                api.initialize()
                mood = load_mood()
                return self._json(200, {
                    "url": os.getenv("VRM_AVATAR_URL", "").strip(),
                    "companion": api.profile.get("companion_name", "NekoSuneAI"),
                    "mood": mood.expression(),
                    "gesture": mood.gesture(),
                    "mood_state": {
                        "valence": round(mood.valence, 3), "arousal": round(mood.arousal, 3),
                        "trust": round(mood.trust, 3), "caution": round(mood.caution, 3),
                    },
                    "local_affect_available": affect.available,
                    "local_affect_error": affect.error if not affect.available else "",
                })
            if parsed.path in {"/mobile", "/mobile/"}:
                relative = "mobile.html"
            elif parsed.path in {"/avatar", "/avatar/"}:
                relative = "vrm.html"
            else:
                relative = "index.html" if parsed.path in {"", "/"} else parsed.path.lstrip("/")
            target = (STATIC_DIR / relative).resolve()
            if STATIC_DIR.resolve() not in target.parents and target != STATIC_DIR.resolve():
                return self.send_error(403)
            if not target.is_file():
                return self.send_error(404)
            body = target.read_bytes()
            if target.name == "index.html":
                body = _decorate_dashboard(body)
            self.send_response(200)
            self.send_header("Content-Type", mimetypes.guess_type(target.name)[0] or "application/octet-stream")
            if target.name in {"vrm.html", "index.html", "mobile.html", "mobile-sw.js", "manifest.webmanifest"}:
                self.send_header("Cache-Control", "no-cache")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    print(f"NekoSuneAI web dashboard: http://{host}:{port}/?token={access_token}")
    print(f"NekoSuneAI mobile dashboard: http://{host}:{port}/mobile?token={access_token}")
    print(f"NekoSuneAI VRM avatar: http://{host}:{port}/avatar?token={access_token}")
    if advertiser.start():
        print(f"NekoSuneAI Android discovery: mDNS _nekosuneai._tcp.local. on port {port}")
    if mobile_notifier:
        print(f"NekoSuneAI Android push: enabled ({mobile_notifier.base_url}/{mobile_notifier.topic}, min={mobile_notifier.min_level})")
    server = ThreadingHTTPServer((host, port), Handler)
    try:
        server.serve_forever()
    finally:
        advertiser.stop()
        server.server_close()
