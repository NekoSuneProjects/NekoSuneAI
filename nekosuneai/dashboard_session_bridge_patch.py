from __future__ import annotations

"""Make the browser dashboard use the admin session cookie instead of ?token=.

The static dashboard predates password/session auth and considers the web API
unavailable unless WEB_TOKEN is populated. When the dashboard is opened on the
HTTPS domain after /login there is intentionally no ?token= anymore, so inject a
compatibility shim before DOMContentLoaded fires.
"""

_INSTALLED = False

_SESSION_BRIDGE = r'''<script id="neko-session-api-bridge">(function(){
if(window.pywebview)return;
let nekoEventCursor=null;
let nekoPolling=false;
try{_apiReady=()=>true}catch(_){}
async function nekoRpc(method,args=[]){
  const response=await fetch('/api/rpc',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify({method,args})});
  if(response.status===401){location.replace('/login?next='+encodeURIComponent(location.pathname||'/'));throw new Error('session expired')}
  const payload=await response.json().catch(()=>({error:'Invalid server response'}));
  if(!response.ok||payload.error)throw new Error(payload.error||('HTTP '+response.status));
  return payload.result;
}
try{pollWebEvents=async function(){
  if(nekoPolling)return;
  nekoPolling=true;
  try{
    // First browser poll starts at the current server cursor. The normal
    // dashboard init separately loads stored chat history, so this avoids
    // replaying/duplicating old messages while preserving all future events.
    if(nekoEventCursor===null){
      nekoEventCursor=Number(await nekoRpc('get_web_event_cursor'))||0;
      return;
    }
    const response=await fetch('/api/events',{credentials:'same-origin',cache:'no-store'});
    if(response.status===401){location.replace('/login?next='+encodeURIComponent(location.pathname||'/'));return}
    if(!response.ok)return;
    const payload=await response.json();
    for(const event of (payload.events||[])){
      const id=Number(event.event_id||0);
      if(id && id<=nekoEventCursor)continue;
      if(id)nekoEventCursor=Math.max(nekoEventCursor,id);
      if(event.type==='state'&&window.__onStateUpdate)window.__onStateUpdate(event.value);
      if(event.type==='chat'&&window.__onChatMessage)window.__onChatMessage(event.value);
      if(event.type==='status'&&window.__onStatusUpdate)window.__onStatusUpdate(event.value);
      if(event.type==='notification'&&window.__onNotification)window.__onNotification(event.value);
      if(event.type==='mobile_alert'&&window.__onNotification)window.__onNotification(event.value);
    }
  }catch(_){}finally{nekoPolling=false}
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

        # Pairing panel also used the removed query token. Session-authenticated
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
