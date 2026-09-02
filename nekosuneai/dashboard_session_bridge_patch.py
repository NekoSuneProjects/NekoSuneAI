from __future__ import annotations

"""Make the browser dashboard use the admin session cookie instead of ?token=.

The static dashboard predates password/session auth and considers the web API
unavailable unless WEB_TOKEN is populated.  When the dashboard is opened on the
HTTPS domain after /login there is intentionally no ?token= anymore, so inject a
small compatibility shim before DOMContentLoaded fires.
"""

_INSTALLED = False

_SESSION_BRIDGE = r'''<script id="neko-session-api-bridge">(function(){
if(window.pywebview)return;
try{_apiReady=()=>true}catch(_){}
try{pollWebEvents=async function(){
  try{
    const response=await fetch('/api/events',{credentials:'same-origin'});
    if(response.status===401){location.replace('/login?next='+encodeURIComponent(location.pathname||'/'));return}
    if(!response.ok)return;
    const payload=await response.json();
    (payload.events||[]).forEach(event=>{
      if(event.type==='state'&&window.__onStateUpdate)window.__onStateUpdate(event.value);
      if(event.type==='chat'&&window.__onChatMessage)window.__onChatMessage(event.value);
      if(event.type==='status'&&window.__onStatusUpdate)window.__onStatusUpdate(event.value);
      if(event.type==='notification'&&window.__onNotification)window.__onNotification(event.value);
    });
  }catch(_){}
}}catch(_){}
})();</script>'''


def install_dashboard_session_bridge_patch() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    from . import webserver

    original = webserver._decorate_dashboard
    if getattr(original, "_neko_session_bridge", False):
        return

    def decorate(body):
        rendered = original(body)
        was_bytes = isinstance(rendered, (bytes, bytearray))
        text = bytes(rendered).decode("utf-8") if was_bytes else str(rendered)

        # Pairing panel also used the removed query token.  Session-authenticated
        # same-origin requests automatically carry the HttpOnly admin cookie.
        text = text.replace(
            "const pairFetch=(url,options={})=>originalFetch(url,{...options,headers:{...(options.headers||{}),'X-Neko-Token':token(),'Content-Type':'application/json'}});",
            "const pairFetch=(url,options={})=>originalFetch(url,{...options,credentials:'same-origin',headers:{...(options.headers||{}),'Content-Type':'application/json'}});",
        )
        text = text.replace(
            "link.href='/automations?token='+encodeURIComponent(token());",
            "link.href='/automations';",
        )
        text = text.replace(
            "if(!panel||!list||!token()){if(panel)panel.classList.add('hidden');return;}",
            "if(!panel||!list){if(panel)panel.classList.add('hidden');return;}",
        )

        marker = "</body>"
        text = text.replace(marker, _SESSION_BRIDGE + marker, 1) if marker in text else text + _SESSION_BRIDGE
        return text.encode("utf-8") if was_bytes else text

    decorate._neko_session_bridge = True
    webserver._decorate_dashboard = decorate
