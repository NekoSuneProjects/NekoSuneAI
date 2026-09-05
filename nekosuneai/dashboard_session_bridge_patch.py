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
let nekoEventCursor=0;
let nekoCursorReady=false;
let nekoPolling=false;
let nekoHistorySignature='';
const nekoRecentChat=new Map();
try{_apiReady=()=>true}catch(_){}

async function nekoRpc(method,args=[]){
  const response=await fetch('/api/rpc',{method:'POST',credentials:'same-origin',cache:'no-store',headers:{'Content-Type':'application/json','Cache-Control':'no-cache'},body:JSON.stringify({method,args})});
  if(response.status===401){location.replace('/login?next='+encodeURIComponent(location.pathname||'/'));throw new Error('session expired')}
  const payload=await response.json().catch(()=>({error:'Invalid server response'}));
  if(!response.ok||payload.error)throw new Error(payload.error||('HTTP '+response.status));
  return payload.result;
}

// Capture the event cursor as soon as this bridge loads, before the user can
// normally start typing. This removes the old first-poll race where messages
// created before cursor initialisation were incorrectly treated as old events.
(async()=>{
  try{nekoEventCursor=Number(await nekoRpc('get_web_event_cursor'))||0}
  catch(_){nekoEventCursor=0}
  finally{nekoCursorReady=true}
})();

function nekoChatKey(msg){
  return String(msg?.role||'')+'\u0000'+String(msg?.text||'');
}
function nekoRememberChat(msg){
  const now=Date.now(),key=nekoChatKey(msg);
  for(const [k,t] of nekoRecentChat){if(now-t>15000)nekoRecentChat.delete(k)}
  if(nekoRecentChat.has(key))return false;
  nekoRecentChat.set(key,now);return true;
}
function nekoInstallChatDedup(){
  const original=window.__onChatMessage;
  if(typeof original!=='function'||original._nekoDedup)return;
  const wrapped=function(msg){if(nekoRememberChat(msg))return original(msg)};
  wrapped._nekoDedup=true;
  window.__onChatMessage=wrapped;
}

async function nekoSyncHistory(){
  try{
    if(typeof window.appendChat!=='function')return;
    const hist=await nekoRpc('get_recent_history');
    if(!Array.isArray(hist))return;
    const sig=JSON.stringify(hist.map(m=>[m.author,m.text,m.role]));
    if(sig===nekoHistorySignature)return;
    nekoHistorySignature=sig;
    const log=document.getElementById('chat-log');
    if(!log)return;
    log.innerHTML='';
    nekoRecentChat.clear();
    for(const m of hist){nekoRememberChat(m);window.appendChat(m.author,m.text,m.role)}
  }catch(_){}
}

// The normal web UI waits for an event to echo a typed message back into chat.
// On the HTTPS/session dashboard show it immediately, then send the RPC. The
// event wrapper above prevents the matching server event from duplicating it.
function nekoInstallSend(){
  window.doSend=async function(){
    const inp=document.getElementById('chat-input');
    if(!inp)return;
    const text=String(inp.value||'').trim();
    if(!text)return;
    inp.value='';
    const optimistic={author:'You',text,role:'user'};
    if(typeof window.__onChatMessage==='function')window.__onChatMessage(optimistic);
    inp.disabled=true;
    const send=document.getElementById('chat-send-btn');if(send)send.disabled=true;
    try{
      const result=await nekoRpc('send_message',[text]);
      if(result&&result.ok===false&&typeof window.showNotification==='function')window.showNotification(result.msg||'Message could not be sent.');
    }catch(e){
      if(typeof window.showNotification==='function')window.showNotification('Chat failed: '+(e?.message||e));
    }finally{
      try{const state=await nekoRpc('get_state');if(window.__onStateUpdate)window.__onStateUpdate(state)}catch(_){}
      setTimeout(nekoSyncHistory,250);
    }
  };
}

try{pollWebEvents=async function(){
  if(nekoPolling||!nekoCursorReady)return;
  nekoPolling=true;
  try{
    const response=await fetch('/api/events',{credentials:'same-origin',cache:'no-store',headers:{'Cache-Control':'no-cache'}});
    if(response.status===401){location.replace('/login?next='+encodeURIComponent(location.pathname||'/'));return}
    if(!response.ok)return;
    const payload=await response.json();
    for(const event of (payload.events||[])){
      const id=Number(event.event_id||0);
      if(id&&id<=nekoEventCursor)continue;
      if(id)nekoEventCursor=Math.max(nekoEventCursor,id);
      if(event.type==='state'&&window.__onStateUpdate)window.__onStateUpdate(event.value);
      if(event.type==='chat'&&window.__onChatMessage)window.__onChatMessage(event.value);
      if(event.type==='status'&&window.__onStatusUpdate)window.__onStatusUpdate(event.value);
      if(event.type==='notification'&&window.__onNotification)window.__onNotification(event.value);
      if(event.type==='mobile_alert'&&window.__onNotification)window.__onNotification(event.value);
    }
  }catch(_){}finally{nekoPolling=false}
}}catch(_){}

function nekoBootSessionBridge(){
  nekoInstallChatDedup();
  nekoInstallSend();
  setTimeout(nekoSyncHistory,400);
  setInterval(nekoSyncHistory,2500);
}
if(document.readyState==='loading')addEventListener('DOMContentLoaded',nekoBootSessionBridge,{once:true});
else nekoBootSessionBridge();
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
