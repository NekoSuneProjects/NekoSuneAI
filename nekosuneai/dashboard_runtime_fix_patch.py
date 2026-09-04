from __future__ import annotations

import threading

_INSTALLED = False


DASHBOARD_RUNTIME_UI = r'''
<style id="neko-runtime-fix-css">
#neko-pairing-modal{position:fixed;inset:0;z-index:250;display:none;align-items:center;justify-content:center;padding:20px;background:rgba(4,5,16,.72);backdrop-filter:blur(10px)}
#neko-pairing-modal.open{display:flex}
#neko-pairing-dialog{width:min(520px,100%);max-height:min(720px,calc(100vh - 40px));overflow:auto;border:1px solid rgba(167,139,250,.35);border-radius:20px;background:linear-gradient(145deg,#181b38,#0d0f24);box-shadow:0 30px 90px rgba(0,0,0,.55)}
.neko-pair-row{padding:13px;border:1px solid rgba(120,126,190,.18);border-radius:13px;background:rgba(8,9,20,.55)}
#neko-device-pairing-nav .pair-count{margin-left:auto;min-width:19px;height:19px;padding:0 6px;display:none;align-items:center;justify-content:center;border-radius:99px;background:#ef4444;color:#fff;font-size:9px;font-weight:800}
#neko-device-pairing-nav.has-pending .pair-count{display:inline-flex}
#vrm-avatar-frame{background:transparent!important;min-height:260px}
#neko-vrm-stage-tools{position:absolute;z-index:40;right:14px;top:14px;display:flex;gap:7px}
#neko-vrm-stage-tools button{backdrop-filter:blur(12px)}
#neko-vrm-upload-status{position:absolute;z-index:40;left:50%;bottom:14px;transform:translateX(-50%);max-width:92%;display:none;padding:7px 10px;border:1px solid rgba(103,232,249,.25);border-radius:10px;background:rgba(8,9,20,.86);color:#c4b5fd;font-size:10px;text-align:center}
</style>
<script id="neko-runtime-fix-js">
(function(){
  const legacyToken=()=>new URLSearchParams(location.search).get('token')||'';
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  async function api(url,options={}){
    const token=legacyToken();
    const headers={...(options.headers||{}),...(options.body instanceof Blob?{}:{'Content-Type':'application/json'})};
    if(token)headers['X-Neko-Token']=token;
    const response=await fetch(url,{...options,credentials:'same-origin',headers});
    if(response.status===401&&!token){location.replace('/login?next='+encodeURIComponent(location.pathname||'/'))}
    return response;
  }

  function mountPairing(){
    if(document.getElementById('neko-pairing-modal'))return;
    const settings=document.querySelector('[data-page="settings"]');
    if(settings){
      const b=document.createElement('button');b.id='neko-device-pairing-nav';b.className='nav-item w-full text-left px-5 py-2.5 text-[13px] text-nova-muted2 border-l-[3px] border-transparent flex items-center gap-2.5';b.innerHTML='<span class="w-5 text-center opacity-70">⌁</span><span>Devices & Pairing</span><span class="pair-count">0</span>';b.onclick=()=>openPairing(true);settings.parentElement.insertBefore(b,settings);
    }
    const modal=document.createElement('div');modal.id='neko-pairing-modal';modal.innerHTML=`<div id="neko-pairing-dialog"><div class="p-5 border-b border-nova-border flex items-start gap-3"><div class="flex-1"><div class="section-kicker">Companion devices</div><div class="text-lg font-bold mt-1">Pair a phone</div><div class="text-[11px] text-nova-muted2 mt-1">When your Android app requests pairing, approve or decline it here.</div></div><button class="btn-secondary px-3 py-2 rounded-lg text-[11px]" onclick="closePairing()">Close</button></div><div class="p-5"><div class="flex items-center justify-between mb-3"><div class="text-[12px] font-bold">Pending requests</div><button class="btn-secondary px-3 py-1.5 rounded-lg text-[10px]" onclick="refreshPairingModal()">Refresh</button></div><div id="neko-pairing-pending" class="space-y-2"><div class="text-[11px] text-nova-muted">Waiting for a phone…</div></div><div class="text-[12px] font-bold mt-5 mb-3">Paired devices</div><div id="neko-pairing-paired" class="space-y-2"><div class="text-[11px] text-nova-muted">No paired devices yet.</div></div></div></div>`;document.body.appendChild(modal);modal.addEventListener('click',e=>{if(e.target===modal)closePairing()});
  }
  window.closePairing=()=>document.getElementById('neko-pairing-modal')?.classList.remove('open');
  window.openPairing=async manual=>{document.getElementById('neko-pairing-modal')?.classList.add('open');await refreshPairingModal(manual)};
  window.pairingAction=async function(action,id,deviceId=''){try{const payload=action==='revoke'?{device_id:deviceId}:{request_id:id};const r=await api('/api/pairing/'+action,{method:'POST',body:JSON.stringify(payload)});const j=await r.json();if(!r.ok)throw new Error(j.error||'Pairing action failed');showNotification?.(action==='approve'?'Phone paired successfully.':action==='reject'?'Pairing request declined.':'Device removed.','success');await refreshPairingModal(true)}catch(e){showNotification?.(e.message,'error')}};
  window.refreshPairingModal=async function(manual=false){
    const pendingWrap=document.getElementById('neko-pairing-pending'),pairedWrap=document.getElementById('neko-pairing-paired'),nav=document.getElementById('neko-device-pairing-nav');if(!pendingWrap||!pairedWrap)return;
    try{
      const [pr,dr]=await Promise.all([api('/api/pairing/pending'),api('/api/pairing/paired')]);const pj=await pr.json(),dj=await dr.json();if(!pr.ok)throw new Error(pj.error||'Unable to read pairing requests');
      const pending=pj.pending||[],paired=dj.paired||[];
      const count=nav?.querySelector('.pair-count');if(count)count.textContent=String(pending.length);nav?.classList.toggle('has-pending',pending.length>0);
      pendingWrap.innerHTML=pending.length?pending.map(x=>`<div class="neko-pair-row"><div class="flex items-start gap-3"><div class="flex-1 min-w-0"><div class="text-[13px] font-semibold">${esc(x.name||'Android phone')}</div><div class="text-[10px] text-nova-muted mt-1">${esc(x.remote_ip||'LAN')} · ${esc(x.device_id||'')}</div></div><span class="live-pill">REQUEST</span></div><div class="grid grid-cols-2 gap-2 mt-3"><button class="btn-primary rounded-lg py-2 text-[11px]" onclick="pairingAction('approve','${esc(x.request_id)}')">Accept</button><button class="btn-danger rounded-lg py-2 text-[11px]" onclick="pairingAction('reject','${esc(x.request_id)}')">Decline</button></div></div>`).join(''):'<div class="text-[11px] text-nova-muted">No pending pairing requests.</div>';
      pairedWrap.innerHTML=paired.length?paired.map(x=>`<div class="neko-pair-row flex items-center gap-3"><div class="flex-1 min-w-0"><div class="text-[12px] font-semibold">${esc(x.name||'Android phone')}</div><div class="text-[9px] text-nova-muted truncate">${esc(x.device_id||'')}</div></div><button class="btn-danger px-3 py-1.5 rounded-lg text-[10px]" onclick="pairingAction('revoke','', '${esc(x.device_id||'')}')">Remove</button></div>`).join(''):'<div class="text-[11px] text-nova-muted">No paired devices yet.</div>';
      if(pending.length&&!manual&&!document.getElementById('neko-pairing-modal')?.classList.contains('open'))openPairing(false);
    }catch(e){if(manual)showNotification?.(e.message,'error')}
  };

  function mountVrmTools(){
    const frame=document.getElementById('vrm-avatar-frame');if(!frame||document.getElementById('neko-vrm-stage-tools'))return;const stage=frame.closest('.avatar-stage');if(!stage)return;
    frame.classList.remove('h-[220px]');frame.classList.add('h-[300px]');
    const tools=document.createElement('div');tools.id='neko-vrm-stage-tools';tools.innerHTML=`<input id="neko-vrm-file" type="file" accept=".vrm,model/gltf-binary" hidden><button class="btn-secondary px-3 py-2 rounded-lg text-[10px]" onclick="document.getElementById('neko-vrm-file').click()">Upload VRM</button><button class="btn-secondary px-3 py-2 rounded-lg text-[10px]" onclick="reloadVrmStage()">Reload</button>`;stage.appendChild(tools);
    const status=document.createElement('div');status.id='neko-vrm-upload-status';stage.appendChild(status);
    document.getElementById('neko-vrm-file').addEventListener('change',async e=>{const file=e.target.files?.[0];if(!file)return;status.style.display='block';status.style.color='';status.textContent='Uploading '+file.name+'…';try{const r=await api('/api/avatar/upload',{method:'POST',headers:{'X-Neko-Filename':file.name,'Content-Type':'model/gltf-binary'},body:file});const j=await r.json();if(!r.ok)throw new Error(j.error||'VRM upload failed');status.textContent='VRM saved — loading transparent avatar…';reloadVrmStage();setTimeout(()=>status.style.display='none',2800)}catch(err){status.textContent=err.message;status.style.color='#fca5a5'}});
  }
  window.reloadVrmStage=function(){const frame=document.getElementById('vrm-avatar-frame');if(frame)frame.src='/avatar?v='+Date.now()};

  addEventListener('DOMContentLoaded',()=>{mountPairing();mountVrmTools();refreshPairingModal(false);setInterval(()=>refreshPairingModal(false),2500)});setTimeout(()=>{mountPairing();mountVrmTools()},80);
})();
</script>
'''


def _install_dashboard_ui() -> None:
    from . import webserver

    original = webserver._decorate_dashboard
    if getattr(original, "_neko_runtime_fix", False):
        return

    def decorated(body: bytes) -> bytes:
        result = original(body)
        text = result.decode("utf-8")
        if "neko-runtime-fix-css" not in text:
            text = text.replace("</body>", DASHBOARD_RUNTIME_UI + "</body>", 1)
        return text.encode("utf-8")

    decorated._neko_runtime_fix = True  # type: ignore[attr-defined]
    webserver._decorate_dashboard = decorated


def _install_tts_busy_recovery() -> None:
    from .webgui import Api

    if getattr(Api, "_neko_tts_busy_recovery", False):
        return

    def speak_async_fixed(self, text: str, emotion: str = "neutral") -> None:
        def worker() -> None:
            try:
                self._speak(text, emotion)
            finally:
                # A finished TTS turn must never leave the dashboard locked in
                # Busy. This is deliberately idempotent: _release() is safe if
                # the normal request path already released the turn first.
                if getattr(self, "busy", False):
                    self._release()
                self._push_status("Ready.")
                try:
                    self._queue_web_event({"type": "avatar_speaking", "value": False})
                except Exception:
                    pass

        threading.Thread(target=worker, daemon=True, name="neko-tts-output").start()

    Api._speak_async = speak_async_fixed
    Api._neko_tts_busy_recovery = True


def install_dashboard_runtime_fix_patch() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _install_dashboard_ui()
    _install_tts_busy_recovery()
    _INSTALLED = True
